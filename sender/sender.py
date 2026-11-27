"""Gönderici - Parça 1: kamera + QR okuma + yerel önizleme (henüz ağ yok)."""
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
    p = argparse.ArgumentParser(description="Gönderici: kamera + QR okuma")
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

            metinler, koseler = decode_qr(detector, frame)
            if metinler and metinler != son_metinler:
                print(f"[kare {kare_no}] QR: {metinler}")
            son_metinler = metinler

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
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()