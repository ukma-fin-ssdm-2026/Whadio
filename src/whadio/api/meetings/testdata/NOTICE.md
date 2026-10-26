# Test recordings

The upload tests use two one-second MP4 files generated for them with FFmpeg's test sources.

## `tone-with-video.mp4`

- **Work:** a 440 Hz tone as AAC, next to a black 64×64 MPEG-4 video.
- **Made with:** `ffmpeg -f lavfi -i "sine=frequency=440:duration=1" -f lavfi
  -i "color=black:size=64x64:rate=10:duration=1" -c:a aac -c:v mpeg4 -shortest
  tone-with-video.mp4`
- **SHA-256:** `e3d04c9793a25a1ae294e3c532afb95a761944ef881690de01ea8e2a0985fc4e`.

## `video-only.mp4`

- **Work:** a black 64×64 MPEG-4 video without an audio track.
- **Made with:** `ffmpeg -f lavfi -i "color=black:size=64x64:rate=10:duration=1" -c:v mpeg4
  -an video-only.mp4`
- **SHA-256:** `692e45eb1f73a9f2937aa54430bf12369ac1e473b1f1f1095087ad9000aafa7a`.
