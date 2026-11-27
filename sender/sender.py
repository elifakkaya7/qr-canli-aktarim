#!/usr/bin/env python3
"""
Gönderici (Bilgisayar 1, webcam'li) - sender/sender.py

Yaptıkları:
  1. Kamerayı açar (640x480@30), her karede QR'ı HAM (sıkıştırılmamış) kare üzerinde okur.
  2. Ham kareyi GStreamer ile H.264'e kodlayıp RTP/UDP ile alıcıya gönderir (port 5000).
  3. QR sonucunu her karede JSON olarak UDP ile gönderir (port 5001); QR yoksa boş liste.
  4. Alıcının geri yolladığı {"kare_no": n} mesajlarını dinler (port 5002) ve
     QR kanalının gecikmesini (RTT/2) ve mesaj kaybını ölçer.
  5. FPS, gecikme ve kaybı terminale ve logs/perf_gonderici_<tarih-saat>.csv'ye yazar.

Bağlantı: iki bilgisayar Ubiquiti Rocket telsiz köprüsü üzerinden kablolu ağda (192.168.1.x).
Telsiz bağlantıda bant genişliği dalgalanır ve paket kaybı olabilir. Bu yüzden:
  - RTP paketleri küçük tutulur (--mtu 1200): telsizde parçalanma ve kayıp azalır.
  - Anahtar kare sıklığı ayarlanabilir (--key-int): kayıptan sonra görüntü daha çabuk düzelir.
  - Bitrate ayarlanabilir (--bitrate): bağlantı zayıfsa düşürün.

Gönderilen JSON (receiver/receiver.py bununla uyumlu):
  {"kare_no": 123, "zaman": 1764240000.123,
   "qr_metinleri": ["metin"], "koseler": [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]],
   "genislik": 640, "yukseklik": 480}
  Konumu bulunup çözülemeyen QR'lar metni "" olarak gönderilir; alıcı onları sarı çizer.

Çalıştırma (proje klasöründen, .venv açıkken; önce alıcı çalışmalı):
  python3 sender/sender.py --host <ALICI-IP> --show
  python3 sender/sender.py --host <ALICI-IP> --bitrate 800 --key-int 15
"""

import argparse
import csv
import json
import os
import socket
import sys
import threading
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np

# common/config.py'yi bulabilmek için proje kök klasörünü arama yoluna ekle
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
from common import config  # noqa: E402

ACK_BEKLEME_SN = 2.0  # Bu sürede ACK gelmeyen QR mesajı "kayıp" sayılır


# ------------------------------------------------------------------ ayarlar
def argumanlar():
    p = argparse.ArgumentParser(description="QR Canlı Aktarım - gönderici")
    p.add_argument("--host", help="Alıcının IP adresi (verilmezse hiçbir şey gönderilmez)")
    p.add_argument("--video-port", type=int, default=config.VIDEO_PORT)
    p.add_argument("--qr-port", type=int, default=config.QR_PORT)
    p.add_argument("--ack-port", type=int, default=config.ACK_PORT)
    p.add_argument("--bitrate", type=int, default=config.BITRATE_KBPS, help="H.264 bitrate (kbit/s)")
    p.add_argument("--key-int", type=int, default=config.KEY_INT_MAX,
                   help="Kaç karede bir anahtar kare (kayıplı bağlantıda küçültün, ör. 15)")
    p.add_argument("--mtu", type=int, default=1200, help="RTP paket boyutu (bayt)")
    p.add_argument("--qr-her", type=int, default=1,
                   help="QR'ı kaç karede bir oku (FPS düşerse 2-3 yapın)")
    p.add_argument("--kamera", type=int, default=0, help="Kamera numarası (/dev/videoN)")
    p.add_argument("--show", action="store_true", help="Kendi ekranında önizleme göster")
    p.add_argument("--log-klasoru", default=os.path.join(KOK, "logs"))
    return p.parse_args()


# ------------------------------------------------------------------ kamera
def kamera_ac(index):
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, config.FPS)
    if not cap.isOpened():
        raise RuntimeError(f"Kamera açılamadı: /dev/video{index} "
                           "(başka bir program kullanıyor olabilir)")
    return cap


# ------------------------------------------------------------------ video (GStreamer)
def gstreamer_hatti(host, port, bitrate, key_int, mtu):
    """Aşama 2'deki gst-launch gönderici komutunun aynısı; kamera (v4l2src) yerine appsrc.
    appsrc = 'kareyi Python'dan al'."""
    return (
        "appsrc ! videoconvert ! video/x-raw,format=I420 ! "
        f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={bitrate} key-int-max={key_int} ! "
        f"rtph264pay config-interval=1 pt={config.RTP_PAYLOAD} mtu={mtu} ! "
        f"udpsink host={host} port={port} sync=false async=false"
    )


def video_yazici_ac(args):
    hat = gstreamer_hatti(args.host, args.video_port, args.bitrate, args.key_int, args.mtu)
    print("GStreamer hattı:", hat)
    yazici = cv2.VideoWriter(hat, cv2.CAP_GSTREAMER, 0, config.FPS,
                             (config.WIDTH, config.HEIGHT), True)
    if not yazici.isOpened():
        raise RuntimeError("GStreamer hattı açılamadı. .venv açık mı? "
                           "OpenCV GStreamer destekli mi? (grep -i gstreamer -> YES)")
    return yazici


# ------------------------------------------------------------------ QR okuma
def qr_oku(dedektor, kare):
    """Ham karedeki QR'ları okur -> (metinler, koseler).
    Önce çoklu okuma; hiçbir şey çözülemezse tek QR okuması yedek olarak denenir
    (OpenCV 4.6'da çoklu okuma bazen QR'ı kaçırıyor).
    Konumu bulunup çözülemeyen QR'lar metni "" ile döner (alıcı sarı çizer)."""
    metinler, koseler = [], []
    ok, texts, points, _ = dedektor.detectAndDecodeMulti(kare)
    if ok and points is not None:
        for text, pts in zip(texts, points):
            metinler.append(text or "")
            koseler.append(pts.reshape(-1, 2).astype(int).tolist())

    if not any(metinler):
        text, pts, _ = dedektor.detectAndDecode(kare)
        if text and pts is not None:
            metinler, koseler = [text], [pts.reshape(-1, 2).astype(int).tolist()]
    return metinler, koseler


def onizleme_ciz(kare, metinler, koseler, fps, gecikme_ms):
    """Sadece yerel önizleme için (kopya üzerine) çizer; ağa ham kare gider."""
    gorunum = kare.copy()
    for metin, kose in zip(metinler, koseler):
        renk = (0, 255, 0) if metin else (0, 255, 255)
        noktalar = np.array(kose, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(gorunum, [noktalar], True, renk, 2)
        x, y = kose[0]
        cv2.putText(gorunum, (metin or "(okunamadi)")[:40], (x, max(y - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, renk, 2)
    bilgi = f"FPS: {fps:.1f}"
    if gecikme_ms is not None:
        bilgi += f"  QR gecikme: {gecikme_ms:.0f} ms"
    cv2.putText(gorunum, bilgi, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return gorunum


# ------------------------------------------------------------------ QR JSON + ACK (UDP)
class QrKanali:
    """QR sonucunu gönderir, alıcıdan dönen kare_no'ları dinler, gecikme ve kaybı hesaplar.

    ACK'ler ayrı bir thread'de dinlenir ve geliş anı hemen not edilir. Böylece ölçülen
    gecikmeye ana döngünün kare bekleme süresi (~33 ms) eklenmez."""

    def __init__(self, host, qr_port, ack_port):
        self.hedef = (host, qr_port)
        self.gonder_soket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ack_soket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ack_soket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ack_soket.bind(("0.0.0.0", ack_port))  # bütün ağ bağlantılarından dinle
        self.ack_soket.settimeout(0.2)               # kapanırken thread takılı kalmasın

        self.gelen_acklar = deque()  # (kare_no, geliş anı) - thread doldurur, ana döngü boşaltır
        self.calisiyor = True
        self.dinleyici = threading.Thread(target=self._ack_dinle, daemon=True)
        self.dinleyici.start()

        self.bekleyen = {}     # kare_no -> gönderim anı (time.monotonic)
        self.rtt_listesi = []  # son penceredeki gidiş-dönüş süreleri (sn)
        self.gonderilen = 0
        self.onaylanan = 0
        self.kayip = 0

    def gonder(self, kare_no, metinler, koseler):
        mesaj = {
            config.KEY_FRAME_NO: kare_no,
            config.KEY_TIME: time.time(),
            config.KEY_TEXTS: metinler,
            config.KEY_CORNERS: koseler,
            "genislik": config.WIDTH,
            "yukseklik": config.HEIGHT,
        }
        veri = json.dumps(mesaj, ensure_ascii=False).encode("utf-8")
        try:
            self.gonder_soket.sendto(veri, self.hedef)
        except OSError as e:  # bağlantı anlık koparsa program durmasın
            print("QR mesajı gönderilemedi:", e)
            return
        self.bekleyen[kare_no] = time.monotonic()
        self.gonderilen += 1

    def _ack_dinle(self):
        """Arka plan thread'i: ACK geldiği anda zamanını kaydeder."""
        while self.calisiyor:
            try:
                veri, _ = self.ack_soket.recvfrom(config.UDP_BUFFER)
            except socket.timeout:
                continue
            except OSError:
                break  # soket kapandı
            self.gelen_acklar.append((self._ack_coz(veri), time.monotonic()))

    def acklari_oku(self):
        """Thread'in topladığı ACK'leri işler; uzun süre cevapsız kalanları kayıp sayar."""
        while self.gelen_acklar:
            kare_no, gelis = self.gelen_acklar.popleft()
            gonderim = self.bekleyen.pop(kare_no, None)
            if gonderim is not None:
                self.rtt_listesi.append(gelis - gonderim)
                self.onaylanan += 1

        simdi = time.monotonic()
        for k in [k for k, t in self.bekleyen.items() if simdi - t > ACK_BEKLEME_SN]:
            del self.bekleyen[k]
            self.kayip += 1

    @staticmethod
    def _ack_coz(veri):
        try:
            metin = veri.decode("utf-8").strip()
            if metin.startswith("{"):
                return int(json.loads(metin)[config.KEY_FRAME_NO])
            return int(metin)
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            return None

    def pencereyi_al(self):
        """Son penceredeki RTT (ort, min, max) ms; ACK yoksa None. Pencereyi sıfırlar."""
        if not self.rtt_listesi:
            return None
        ms = [r * 1000 for r in self.rtt_listesi]
        self.rtt_listesi = []
        return sum(ms) / len(ms), min(ms), max(ms)

    def kayip_yuzde(self):
        biten = self.onaylanan + self.kayip
        return 100.0 * self.kayip / biten if biten else 0.0

    def kapat(self):
        self.calisiyor = False
        self.dinleyici.join(timeout=1.0)
        self.gonder_soket.close()
        self.ack_soket.close()


# ------------------------------------------------------------------ ana program
def main():
    args = argumanlar()
    cap = kamera_ac(args.kamera)
    dedektor = cv2.QRCodeDetector()

    yazici = kanal = None
    perf_dosya = perf_yazici = None
    if args.host:
        yazici = video_yazici_ac(args)
        kanal = QrKanali(args.host, args.qr_port, args.ack_port)
        print(f"Gönderiliyor -> {args.host}  video:{args.video_port}  "
              f"qr:{args.qr_port}  ack:{args.ack_port}")

        os.makedirs(args.log_klasoru, exist_ok=True)
        damga = datetime.now().strftime("%Y%m%d_%H%M%S")
        yol = os.path.join(args.log_klasoru, f"perf_gonderici_{damga}.csv")
        perf_dosya = open(yol, "w", newline="", encoding="utf-8")
        perf_yazici = csv.writer(perf_dosya)
        perf_yazici.writerow([
            "zaman", "fps", "qr_rtt_ort_ms", "qr_rtt_min_ms", "qr_rtt_max_ms", "qr_gecikme_ms",
            "gonderilen", "onaylanan", "kayip", "kayip_yuzde", "bitrate_kbps", "key_int", "mtu"])
        print("Performans kaydı:", yol)
    else:
        print("--host verilmedi: hiçbir şey gönderilmiyor, sadece yerel çalışıyor.")

    kare_no = 0
    fps = 0.0
    gecikme_ms = None
    sayac, pencere_bas = 0, time.time()
    metinler, koseler, son_metinler = [], [], []

    try:
        while True:
            ret, kare = cap.read()
            if not ret:
                print("Kameradan kare alınamadı, çıkılıyor.")
                break
            kare_no += 1

            # GStreamer sabit boyut bekliyor
            if kare.shape[1] != config.WIDTH or kare.shape[0] != config.HEIGHT:
                kare = cv2.resize(kare, (config.WIDTH, config.HEIGHT))

            # --- QR: ham kare üzerinde (--qr-her karede bir; arada son sonuç kullanılır) ---
            if kare_no % args.qr_her == 0:
                metinler, koseler = qr_oku(dedektor, kare)
                okunan = [m for m in metinler if m]
                if okunan and okunan != son_metinler:
                    print(f"[kare {kare_no}] QR: {okunan}")
                son_metinler = okunan

            # --- Ağa: HAM (çizimsiz) kare + QR JSON; çizimi alıcı yapar ---
            if yazici is not None:
                yazici.write(kare)
            if kanal is not None:
                kanal.gonder(kare_no, metinler, koseler)
                kanal.acklari_oku()

            # --- Saniyede bir: FPS, gecikme, kayıp ---
            sayac += 1
            gecen = time.time() - pencere_bas
            if gecen >= 1.0:
                fps = sayac / gecen
                sayac, pencere_bas = 0, time.time()
                satir = f"FPS: {fps:.1f}"

                if kanal is not None:
                    pencere = kanal.pencereyi_al()
                    if pencere:
                        ort, mn, mx = pencere
                        gecikme_ms = ort / 2
                        satir += (f" | QR RTT ort {ort:.0f} ms (min {mn:.0f}, max {mx:.0f})"
                                  f" -> gecikme ~{gecikme_ms:.0f} ms")
                    else:
                        ort = mn = mx = None
                        satir += " | ACK gelmiyor (alıcı çalışıyor mu?)"
                    satir += f" | QR kayıp %{kanal.kayip_yuzde():.1f}"

                    bos = lambda v: "" if v is None else round(v, 1)  # noqa: E731
                    perf_yazici.writerow([
                        datetime.now().isoformat(timespec="milliseconds"), round(fps, 1),
                        bos(ort), bos(mn), bos(mx), bos(None if ort is None else ort / 2),
                        kanal.gonderilen, kanal.onaylanan, kanal.kayip,
                        round(kanal.kayip_yuzde(), 2), args.bitrate, args.key_int, args.mtu])
                    perf_dosya.flush()  # program çökerse kayıtlar kaybolmasın
                print(satir)

            if args.show:
                cv2.imshow("Gonderici onizleme",
                           onizleme_ciz(kare, metinler, koseler, fps, gecikme_ms))
                if cv2.waitKey(1) & 0xFF == ord("q"):  # q tuşu ile çık
                    break

    except KeyboardInterrupt:
        pass  # Ctrl+C ile de düzgün kapansın
    finally:
        cap.release()            # kamera "meşgul" kalmasın
        if yazici is not None:
            yazici.release()     # GStreamer hattını kapat
        if kanal is not None:
            print(f"Özet: gönderilen {kanal.gonderilen}, onaylanan {kanal.onaylanan}, "
                  f"kayıp {kanal.kayip} (%{kanal.kayip_yuzde():.1f})")
            kanal.kapat()
        if perf_dosya is not None:
            perf_dosya.close()
        cv2.destroyAllWindows()
        print("Gönderici kapandı.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
