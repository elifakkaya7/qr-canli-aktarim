#!/usr/bin/env python3
"""
Alıcı (yer istasyonu) - receiver/receiver.py

Yaptıkları:
  1. GStreamer ile UDP 5000'den gelen RTP/H.264 görüntüyü karelere çevirir.
  2. UDP 5001'den gelen QR sonuçlarını (JSON) okur.
  3. En son QR bilgisini kareye çizer, ekranda gösterir.
  4. Okunan QR'ları ve performans bilgisini logs/ altına CSV olarak kaydeder.
  5. Gecikme ölçümü için her JSON'un kare_no'sunu göndericiye (UDP 5002) geri yollar.

Göndericinin göndermesi gereken JSON formatı:
  {
    "kare_no": 123,                       # her karede 1 artan sayı
    "zaman": 1764240000.123,              # göndericide time.time()
    "qr_metinleri": ["metin1", "metin2"], # QR yoksa boş liste []
    "koseler": [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], ...],  # her QR için 4 köşe
    "genislik": 640, "yukseklik": 480     # (isteğe bağlı) göndericinin kare boyutu
  }

Çalıştırma (proje klasöründen, .venv açıkken):
  python3 receiver/receiver.py
"""

import argparse
import csv
import json
import os
import socket
import sys
import time
from datetime import datetime

import cv2
import numpy as np

# common/config.py'yi bulabilmek için proje kök klasörünü Python'un arama yoluna ekliyoruz.
# (Dosyayı "python3 receiver/receiver.py" ile çalıştırınca Python sadece receiver/ klasörüne bakar.)
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
from common import config  # noqa: E402

QR_ESKIME_SN = 0.5  # Bundan eski QR bilgisini çizme (QR artık kadrajda olmayabilir)
TEKRAR_SN = 2.0     # Aynı QR bu kadar saniye görünmeyip geri gelirse tekrar kaydet


def gstreamer_hatti(port):
    """Aşama 2'deki gst-launch alıcı komutunun aynısı; sadece sonu ekran yerine appsink.
    appsink = 'kareyi Python'a ver'. drop=true max-buffers=1 -> yetişemezsek eski kareleri at,
    hep en yenisini al; böylece gecikme birikmez."""
    return (
        f"udpsrc port={port} "
        'caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" ! '
        "rtpjitterbuffer latency=0 ! rtph264depay ! avdec_h264 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def qr_ciz(kare, mesaj):
    """JSON'daki köşe noktalarından QR kutusunu ve metnini kareye çizer."""
    h, w = kare.shape[:2]
    # Gönderici farklı çözünürlükte çalışıyorsa köşeleri bizim kare boyutumuza ölçekle
    sx = w / mesaj.get("genislik", w)
    sy = h / mesaj.get("yukseklik", h)

    for metin, kose in zip(mesaj.get("qr_metinleri", []), mesaj.get("koseler", [])):
        noktalar = np.array(kose, dtype=np.float32).reshape(-1, 2)
        noktalar[:, 0] *= sx
        noktalar[:, 1] *= sy
        noktalar = noktalar.astype(np.int32)

        renk = (0, 255, 0) if metin else (0, 255, 255)  # okunduysa yeşil, okunamadıysa sarı
        cv2.polylines(kare, [noktalar], True, renk, 2)
        x, y = noktalar[0]
        yazi = metin if metin else "(okunamadi)"
        # Not: cv2.putText Türkçe harfleri (ş, ğ, İ...) '?' olarak çizer; CSV'de doğru kaydedilir.
        cv2.putText(kare, yazi, (int(x), max(int(y) - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, renk, 2)


def main():
    parser = argparse.ArgumentParser(description="QR Canlı Aktarım - alıcı")
    parser.add_argument("--video-port", type=int, default=config.VIDEO_PORT)
    parser.add_argument("--qr-port", type=int, default=config.QR_PORT)
    parser.add_argument("--ack-port", type=int, default=config.ACK_PORT)
    parser.add_argument("--log-klasoru", default=os.path.join(KOK, "logs"))
    args = parser.parse_args()

    # --- Kayıt dosyaları: her çalıştırma ayrı dosya (adında tarih-saat var) ---
    os.makedirs(args.log_klasoru, exist_ok=True)
    damga = datetime.now().strftime("%Y%m%d_%H%M%S")

    qr_dosya = open(os.path.join(args.log_klasoru, f"qr_{damga}.csv"),
                    "w", newline="", encoding="utf-8")
    qr_yazici = csv.writer(qr_dosya)
    qr_yazici.writerow(["zaman", "kare_no", "qr_metni", "gonderici_zamani"])

    perf_dosya = open(os.path.join(args.log_klasoru, f"perf_alici_{damga}.csv"),
                      "w", newline="", encoding="utf-8")
    perf_yazici = csv.writer(perf_dosya)
    perf_yazici.writerow(["zaman", "fps", "alinan_qr_mesaji", "beklenen_qr_mesaji", "kayip_yuzde"])

    # --- QR kanalı: UDP soket, bloklamayan ---
    # Bloklamayan = mesaj yoksa beklemez, video döngüsü donmaz.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.qr_port))  # 0.0.0.0 = bilgisayarın bütün ağ bağlantılarından dinle
    sock.setblocking(False)

    # --- Video kanalı: GStreamer ---
    print(f"Video hattı açılıyor (UDP {args.video_port})... Göndericiyi başlatın.")
    cap = cv2.VideoCapture(gstreamer_hatti(args.video_port), cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("HATA: Video hattı açılamadı.")
        print(" - .venv açık mı? (source .venv/bin/activate)")
        print(" - OpenCV GStreamer destekli mi? (grep -i gstreamer -> YES olmalı)")
        return 1

    son_qr = None          # en son gelen JSON mesajı
    son_qr_gelis = 0.0     # o mesajın geldiği an
    son_gorulme = {}       # her QR metninin en son görüldüğü an (tekrarları ayıklamak için)

    ilk_kare_no = None     # kayıp hesabı için: ilk ve son kare numarası, gelen mesaj sayısı
    son_kare_no = None
    alinan = 0

    sayac = 0              # FPS hesabı için
    pencere_bas = time.time()
    fps = 0.0

    try:
        while True:
            ret, kare = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # --- Gelmiş bütün QR mesajlarını oku, en sonuncuyu tut ---
            while True:
                try:
                    veri, adres = sock.recvfrom(65535)
                except BlockingIOError:
                    break  # okunacak mesaj kalmadı
                try:
                    mesaj = json.loads(veri.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue  # bozuk mesajı atla

                kare_no = mesaj.get("kare_no")
                if kare_no is not None:
                    # Gönderici yeniden başlatıldıysa sayaçları sıfırla
                    if son_kare_no is None or kare_no < son_kare_no:
                        ilk_kare_no = kare_no
                        alinan = 0
                    son_kare_no = kare_no
                    alinan += 1
                    # Gecikme ölçümü: kare_no'yu göndericiye geri yolla (o RTT/2 hesaplar)
                    sock.sendto(json.dumps({"kare_no": kare_no}).encode("utf-8"),
                                (adres[0], args.ack_port))

                son_qr = mesaj
                son_qr_gelis = time.time()

                # --- Kaydet: sadece yeni QR ya da bir süre görünmeyip geri gelen QR ---
                simdi = time.time()
                for metin in mesaj.get("qr_metinleri", []):
                    if not metin:
                        continue
                    if simdi - son_gorulme.get(metin, 0) > TEKRAR_SN:
                        qr_yazici.writerow([
                            datetime.now().isoformat(timespec="milliseconds"),
                            kare_no, metin, mesaj.get("zaman")])
                        qr_dosya.flush()  # program çökerse kayıtlar kaybolmasın
                        print(f"[QR] {metin}")
                    son_gorulme[metin] = simdi

            # --- Çiz: QR bilgisi yeterince tazeyse ---
            if son_qr is not None and time.time() - son_qr_gelis <= QR_ESKIME_SN:
                qr_ciz(kare, son_qr)

            # --- FPS ve kayıp: saniyede bir hesapla ve kaydet ---
            sayac += 1
            gecen = time.time() - pencere_bas
            if gecen >= 1.0:
                fps = sayac / gecen
                sayac = 0
                pencere_bas = time.time()

                beklenen = (son_kare_no - ilk_kare_no + 1) if ilk_kare_no is not None else 0
                kayip = 100.0 * (1 - alinan / beklenen) if beklenen > 0 else 0.0
                perf_yazici.writerow([
                    datetime.now().isoformat(timespec="milliseconds"),
                    round(fps, 1), alinan, beklenen, round(kayip, 2)])
                perf_dosya.flush()

            cv2.putText(kare, f"FPS: {fps:.1f}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow("Alici - QR Canli Aktarim", kare)

            if cv2.waitKey(1) & 0xFF == ord("q"):  # q tuşu ile çık
                break

    except KeyboardInterrupt:
        pass  # Ctrl+C ile de düzgün kapansın
    finally:
        cap.release()
        sock.close()
        qr_dosya.close()
        perf_dosya.close()
        cv2.destroyAllWindows()
        print("Alıcı kapandı. Kayıtlar:", args.log_klasoru)

    return 0


if __name__ == "__main__":
    sys.exit(main())