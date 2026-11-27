# QR Canlı Aktarım

Bir bilgisayardaki webcam görüntüsünü GStreamer (RTP/H.264) ile ikinci bilgisayara gerçek zamanlı aktaran,
QR kodlarını göndericide çözüp sonucu ayrı bir UDP kanalıyla (JSON) gönderen sistem.

> Bu README geliştirme sırasında doldurulacaktır.

## Mimari
_TODO_

## Gereksinimler
- Ubuntu 24.04 ve test edilen diğer sistemler, Python 3.12, webcam, iki bilgisayar aynı ağda
- apt paketleri:
  ```bash
  sudo apt install gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    python3-opencv python3-numpy v4l-utils
  ```

## Kurulum
```bash
Conda/venv açıksa önce conda deactivate / deactivate yapın; which python3 çıktısı /usr/bin/python3

/usr/bin/python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "import cv2; print(cv2.getBuildInformation())" | grep -i gstreamer   # YES görünmeli
```

## Çalıştırma
_TODO_

## Performans sonuçları
_TODO_

## Sınırlamalar
_TODO_
