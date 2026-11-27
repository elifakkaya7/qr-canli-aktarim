"""Gönderici (Bilgisayar 1, webcam'li).

Görevleri:
1. Kamerayı OpenCV ile açar (cv2.VideoCapture), 640x480 kare alır.
2. QR kodlarını ham (sıkıştırılmamış) kare üzerinde çözer
   (cv2.QRCodeDetector().detectAndDecodeMulti).
3. Kareyi GStreamer hattına verir: appsrc -> x264enc -> rtph264pay -> udpsink
   (port common.config.VIDEO_PORT).
4. QR sonucunu JSON olarak UDP ile gönderir (port common.config.QR_PORT).
   QR yoksa da boş liste gönderir.
5. ACK_PORT'tan dönen kare_no ile QR kanalının gecikmesini (RTT/2) ölçer.
6. FPS'i terminale yazar.

Çalıştırma (planlanan):
    python sender/sender.py --host <ALICI-IP> --bitrate 1500
"""


def main():
    raise NotImplementedError("Aşama 3'te yazılacak")


if __name__ == "__main__":
    main()
