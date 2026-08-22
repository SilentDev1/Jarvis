#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p data/models
curl -fL --retry 3 \
  -o data/models/face_detection_yunet_2026may.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2026may.onnx
curl -fL --retry 3 \
  -o data/models/face_recognition_sface_2021dec.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
echo "Local YuNet/SFace models installed in excluded data/models/."
