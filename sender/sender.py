"""Gönderici - Parça 2: kamera + QR okuma + GStreamer ile H.264/RTP görüntü gönderimi."""
import argparse
import os
import sys
import time

import cv2
import numpy as np

# "python sender/sender.py" ile çalışınca common/ klasörünü bulabilmek için
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import config  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Gönderici: kamera + QR okuma + görüntü gönderimi")
    p.add_argument("--host", help="Alıcının IP adresi (verilmezse görüntü gönderilmez)")
    p.add_argument("--port", type=int, default=config.VIDEO_PORT, help="Video portu")
    p.add_argument("--bitrate", type=int, default=config.BITRATE_KBPS, help="H.264 bitrate (kbit/s)")
    p.add_argument("--key-int", type=int, default=config.KEY_INT_MAX, help="Kaç karede bir anahtar kare")
    p.add_argument("--camera", type=int, default=0, help="Kamera numarası (/dev/videoN)")
    p.add_argument("--show", action="store_true", help="Kendi ekranında önizleme göster")
    return p.parse_args()


def open_camera(index):
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, config.FPS)
    if not cap.isOpened():
        raise RuntimeError(f"Kamera açılamadı: /dev/video{index}")
    return cap


def build_pipeline(host, port, bitrate, key_int):
    """Aşama 2'deki gönderici gst-launch komutunun aynısı; v4l2src yerine appsrc (kare Python'dan gelir)."""
    return (
        "appsrc ! videoconvert ! video/x-raw,format=I420 ! "
        f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={bitrate} key-int-max={key_int} ! "
        f"rtph264pay config-interval=1 pt={config.RTP_PAYLOAD} ! "
        f"udpsink host={host} port={port} sync=false"
    )


def open_writer(args):
    pipeline = build_pipeline(args.host, args.port, args.bitrate, args.key_int)
    print("GStreamer hattı:", pipeline)
    writer = cv2.VideoWriter(pipeline, cv2.CAP_GSTREAMER, 0, config.FPS,
                             (config.WIDTH, config.HEIGHT), True)
    if not writer.isOpened():
        raise RuntimeError("GStreamer hattı açılamadı. OpenCV'de GStreamer desteği YES mi? "
                           "(.venv etkin mi, pip'teki opencv-python kurulu olmamalı)")
    return writer


def decode_qr(detector, frame):
    """Ham karedeki QR'ları okur. (metinler, koseler) döndürür; QR yoksa iki boş liste."""
    ok, texts, points, _ = detector.detectAndDecodeMulti(frame)
    if not ok or points is None:
        return [], []
    metinler, koseler = [], []
    for text, pts in zip(texts, points):
        if text:  # bulunup çözülemeyen QR'lar boş metin döner, onları atla
            metinler.append(text)
            koseler.append(pts.astype(int).tolist())
    return metinler, koseler


def draw_preview(frame, metinler, koseler, fps):
    """Sadece yerel önizleme için çizer; ağa ham kare gidecek."""
    view = frame.copy()
    for text, pts in zip(metinler, koseler):
        poly = np.array(pts, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(view, [poly], True, (0, 255, 0), 2)
        x, y = pts[0]
        cv2.putText(view, text[:40], (x, max(y - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.putText(view, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    return view


def main():
    args = parse_args()
    cap = open_camera(args.camera)
    detector = cv2.QRCodeDetector()
    writer = open_writer(args) if args.host else None
    if writer is None:
        print("--host verilmedi: görüntü gönderilmiyor, sadece yerel çalışıyor.")

    kare_no = 0
    fps = 0.0
    sayac, t0 = 0, time.time()
    son_metinler = []

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Kare alınamadı, çıkılıyor.")
                break
            kare_no += 1

            # Kamera farklı boyut verirse GStreamer'a beklediği boyutu ver
            if frame.shape[1] != config.WIDTH or frame.shape[0] != config.HEIGHT:
                frame = cv2.resize(frame, (config.WIDTH, config.HEIGHT))

            metinler, koseler = decode_qr(detector, frame)
            if metinler and metinler != son_metinler:
                print(f"[kare {kare_no}] QR: {metinler}")
            son_metinler = metinler

            # Ağa HAM (çizimsiz) kare gider; çizimi alıcı yapar
            if writer is not None:
                writer.write(frame)

            # FPS: saniyede bir güncelle
            sayac += 1
            gecen = time.time() - t0
            if gecen >= 1.0:
                fps = sayac / gecen
                print(f"FPS: {fps:.1f}")
                sayac, t0 = 0, time.time()

            if args.show:
                cv2.imshow("Gonderici onizleme", draw_preview(frame, metinler, koseler, fps))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()          # kamera "meşgul" kalmasın
        if writer is not None:
            writer.release()   # GStreamer hattını kapat
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()