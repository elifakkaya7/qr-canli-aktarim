"""Alıcı (Bilgisayar 2, yer istasyonu).

Görevleri:
1. H.264 görüntüyü GStreamer ile alır: udpsrc -> rtph264depay -> avdec_h264
   -> appsink (cv2.VideoCapture(..., cv2.CAP_GSTREAMER), port common.config.VIDEO_PORT).
2. QR JSON mesajlarını UDP'den okur (port common.config.QR_PORT, bloklamayan soket),
   en son geleni tutar.
3. Her kareye en son QR bilgisini çizer (QR_MAX_AGE_S'den eskiyse çizmez):
   köşelerden kutu, QR metni, FPS.
4. Görüntüyü gösterir (cv2.imshow), q ile çıkar.
5. Okunan QR'ları logs/qr_<tarih-saat>.csv'ye, ölçümleri logs/perf_<tarih-saat>.csv'ye kaydeder.
6. Gelen her kare_no'yu ACK_PORT'tan göndericiye geri yollar (gecikme ölçümü).

Çalıştırma (planlanan):
    python receiver/receiver.py
"""


def main():
    raise NotImplementedError("Aşama 4'te yazılacak")


if __name__ == "__main__":
    main()
