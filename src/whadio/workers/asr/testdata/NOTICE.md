# Test recordings

The transcription tests use two short recordings of read speech and one generated tone. The
tests that need two speakers join the speech clips in memory; no joined file is stored.

## `uk-bylyna.flac`

- **Work:** «Билина», a fable by Leonid Hlibov (1858), read by radar for LibriVox.
- **Licence:** public domain (a LibriVox recording of a public-domain text).
- **Source:** <https://archive.org/details/fables_glibov_1212_librivox>, file
  `baiky_002_glibov.ogg` (SHA-256
  `ad78f1fb4fc57998900c709254a6f178012e75d839266f5345805a20007e5e60`).
- **Changes:** cut to the excerpt from 23.4 s to 39.0 s and re-encoded as mono 16 kHz FLAC.
- **SHA-256:** `b0564116cb8122588da228b63e624898725f775c5509554d43a15dc58d4d0ddc`.
- **Text:** «— Ох, Кущику! — Билина каже. — Я на чужині… Хто щиро поважа родину, Свій рідний
  край, Тому не всюди рай: Чужина в'ялить, як билину.»

## `en-2277-149896-0032.flac`

- **Work:** LibriSpeech ASR corpus, utterance `2277-149896-0032` of `dev-clean`,
  © 2014 Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur.
- **Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- **Source:** `dev-clean.tar.gz` from <https://www.openslr.org/12>.
- **Changes:** none.
- **SHA-256:** `56b640a079f27f9473478a20f068b8bd8af3afa7030d7a07cbbc7b3f19211689`.
- **Text:** "BY THE TIME HE REACHED HIS OWN STREET HE WAS KEENLY ALIVE TO THE DIFFICULTIES OF HIS
  SITUATION AND WISHED OVER AND OVER THAT SOME SOLUTION WOULD OFFER ITSELF THAT HE COULD SEE HIS
  WAY OUT"

## `tone-live.webm`

- **Work:** a 2-second 440 Hz tone generated for these tests with PyAV, encoded as Opus in WebM
  in live mode, as a browser's MediaRecorder writes a recording: the file declares no duration.
- **SHA-256:** `6b24c028457bf38d88ae436eea7417abba952c5f8c3aeac0b1b6c410e45f8d0f`.
