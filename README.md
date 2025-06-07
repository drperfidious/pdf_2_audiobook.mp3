# PDF to Audiobook

This project converts a written PDF into a narrated audiobook using Google Cloud Text-to-Speech. The script detects quoted dialog, determines a probable gender for each speaker and picks an appropriate voice.

## Features

- Extracts text from PDF documents
- Splits narration and dialogue while attributing quotes to the latest speaker when unlabeled
- Uses gender detection to choose male or female voices from the configured pool
- Chunks long passages so each request stays under the API character limit
- Produces a single MP3 audiobook along with individual segment files

## Installation

1. Install [FFmpeg](https://ffmpeg.org/) and make sure the `ffmpeg` binary is on your PATH.
2. Install Python dependencies:

```bash
pip install PyPDF2 pydub spacy python-dotenv gender-guesser google-cloud-texttospeech
python -m spacy download en_core_web_sm
```

## Google Cloud Setup

Create a Google Cloud service account with the Text‑to‑Speech API enabled and set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to the path of the JSON key file.

## Configuration

The script reads several options from a `.env` file or the environment:

- `GCP_MALE_VOICES` – comma‑separated list of male voice IDs
- `GCP_FEMALE_VOICES` – comma‑separated list of female voice IDs
- `GCP_DEFAULT_VOICE` – default voice used when no gendered voice is found
- `GCP_SPEAKING_RATE` – speed multiplier (default `1.0`)
- `GCP_PITCH` – pitch adjustment in semitones (default `0.0`)

Example `.env`:

```dotenv
GCP_MALE_VOICES=en-US-Polyglot-1,en-US-Neural2-B
GCP_FEMALE_VOICES=en-US-Neural2-C,en-US-Neural2-F
GCP_DEFAULT_VOICE=en-US-Neural2-C
```

## Usage

Run the script with an input PDF and an output MP3 filename:

```bash
python3 pdf_to_gendered_audiobook.py book.pdf audiobook.mp3
```

During processing the script prints which segment is being synthesized and exports each segment to `<output>_chunks/` before combining everything into the final MP3.

## License

This project is released under the MIT License.
