#!/usr/bin/env python3
"""
Usage:
    python3 pdf_to_gendered_audiobook.py input.pdf output.mp3

Dependencies:
    pip install PyPDF2 pydub spacy python-dotenv gender-guesser google-cloud-texttospeech
    python -m spacy download en_core_web_sm
    ffmpeg installed and on your PATH (for pydub)
    Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON.
"""

import os
import re
import sys
from io import BytesIO
from collections import Counter

from dotenv import load_dotenv
from PyPDF2 import PdfReader
from pydub import AudioSegment
import spacy
import gender_guesser.detector as gd
from google.cloud import texttospeech

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION & AUTH
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
raw_male   = os.getenv("GCP_MALE_VOICES", "")
raw_female = os.getenv("GCP_FEMALE_VOICES", "")
GCP_MALE_VOICES   = [v for v in raw_male.split(",") if v.strip()]
GCP_FEMALE_VOICES = [v for v in raw_female.split(",") if v.strip()]
GCP_DEFAULT_VOICE = os.getenv("GCP_DEFAULT_VOICE")
if not GCP_DEFAULT_VOICE:
    if GCP_MALE_VOICES:
        GCP_DEFAULT_VOICE = GCP_MALE_VOICES[0]
    elif GCP_FEMALE_VOICES:
        GCP_DEFAULT_VOICE = GCP_FEMALE_VOICES[0]
    else:
        print("Error: No default voice configured.")
        sys.exit(1)

SPEAKING_RATE = float(os.getenv("GCP_SPEAKING_RATE", "1.0"))
PITCH         = float(os.getenv("GCP_PITCH", "0.0"))
MAX_CHARS     = 3000

nlp        = spacy.load("en_core_web_sm")
gdet      = gd.Detector(case_sensitive=False)
gcp_client = texttospeech.TextToSpeechClient()

# ──────────────────────────────────────────────────────────────────────────────
# TEXT EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────
def extract_text_from_pdf(path):
    reader = PdfReader(path)
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)

# ──────────────────────────────────────────────────────────────────────────────
# SEGMENT TEXT BY SPEAKER WITH POST-QUOTE ATTRIBUTION
# ──────────────────────────────────────────────────────────────────────────────
QUOTE_PATTERN = re.compile(
    r'“([^”]+)”',
    re.IGNORECASE
)
ATTRIB_PATTERN = re.compile(r"^\s*(\w+)\s*(?:said|asked|shouted|replied)", re.IGNORECASE)

def split_segments(text):
    raw_segments = []
    last = 0
    for m in QUOTE_PATTERN.finditer(text):
        start, end = m.span()
        # Narration preceding any quote
        if start > last:
            raw_segments.append((None, text[last:start]))
        quote = m.group(0)
        speaker_tag = None
        # Check immediate inline tag (e.g., , Name said)
        inline = re.search(r',\s*(\w+)\s*(?:said|asked|shouted|replied)', text[end:end+50], re.IGNORECASE)
        if inline:
            speaker_tag = inline.group(1)
            end += inline.end()
        else:
            # Check post-quote attribution beyond inline
            post = text[end:end+100]
            post_match = ATTRIB_PATTERN.match(post)
            if post_match:
                speaker_tag = post_match.group(1)
                end += post_match.end()
        raw_segments.append((speaker_tag, quote))
        last = end
    # Remaining narration
    if last < len(text):
        raw_segments.append((None, text[last:]))
    # Propagate speaker to unlabeled quotes
    segments = []
    last_speaker = None
    for speaker, seg_text in raw_segments:
        if seg_text.startswith('“'):
            # Dialogue segment
            if speaker:
                last_speaker = speaker
                segments.append((speaker, seg_text))
            elif last_speaker:
                segments.append((last_speaker, seg_text))
            else:
                segments.append((None, seg_text))
        else:
            # Narration segment
            segments.append((None, seg_text))
    return segments

# ──────────────────────────────────────────────────────────────────────────────
# CHUNK SEGMENTS TO SIZE
# ──────────────────────────────────────────────────────────────────────────────

def chunk_segment(speaker, segment_text, max_chars=MAX_CHARS):
    subchunks = []
    if len(segment_text) <= max_chars:
        return [(speaker, segment_text)]
    buf = ""
    for sent in re.split(r'(?<=[.?!])\s+', segment_text):
        if len(buf) + len(sent) + 1 > max_chars:
            subchunks.append((speaker, buf.strip()))
            buf = sent + ' '
        else:
            buf += sent + ' '
    if buf.strip():
        subchunks.append((speaker, buf.strip()))
    return subchunks

# ──────────────────────────────────────────────────────────────────────────────
# SPEAKER & GENDER UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def guess_gender(name):
    if not name:
        return None
    nl = name.lower()
    if nl in ('he','him','his'):
        return 'male'
    if nl in ('she','her','hers'):
        return 'female'
    first = name.split()[0]
    g = gdet.get_gender(first)
    if g in ('male','mostly_male'):   return 'male'
    if g in ('female','mostly_female'): return 'female'
    return None



def assign_voice(speaker):
    if speaker is None:
        return GCP_DEFAULT_VOICE
    gender = guess_gender(speaker)
    if gender == "male" and GCP_MALE_VOICES:
        return GCP_MALE_VOICES.pop(0)
    if gender == "female" and GCP_FEMALE_VOICES:
        return GCP_FEMALE_VOICES.pop(0)
    return GCP_DEFAULT_VOICE

# ──────────────────────────────────────────────────────────────────────────────
# TTS SYNTHESIS
# ──────────────────────────────────────────────────────────────────────────────
def synthesize_text(text, voice_name):
    if not voice_name:
        voice_name = GCP_DEFAULT_VOICE
    parts = voice_name.split('-')
    if len(parts) >= 2:
        language_code = f"{parts[0].lower()}-{parts[1].lower()}"
    else:
        language_code = parts[0].lower()
    input_text = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        name=voice_name,
        language_code=language_code
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=SPEAKING_RATE,
        pitch=PITCH
    )
    resp = gcp_client.synthesize_speech(
        input=input_text, voice=voice, audio_config=audio_config
    )
    return AudioSegment.from_file(BytesIO(resp.audio_content), format="mp3")

# ──────────────────────────────────────────────────────────────────────────────
# MAIN ORCHESTRATION
# ──────────────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) != 3:
        print("Usage: pdf_to_gendered_audiobook.py input.pdf output.mp3")
        sys.exit(1)
    pdf_path, out_mp3 = sys.argv[1], sys.argv[2]
    if not os.path.isfile(pdf_path):
        print(f"Error: file not found: {pdf_path}")
        sys.exit(1)

    text = extract_text_from_pdf(pdf_path)
    segments = split_segments(text)

    chunks = []
    for speaker, seg_text in segments:
        chunks.extend(chunk_segment(speaker, seg_text))

    base = os.path.splitext(out_mp3)[0]
    os.makedirs(f"{base}_chunks", exist_ok=True)
    partial = f"{base}_partial.mp3"
    book = AudioSegment.empty()

    speaker_to_voice = {}
    print(f"Total segments: {len(chunks)}")
    for i, (spk, txt) in enumerate(chunks, 1):
        if spk not in speaker_to_voice:
            speaker_to_voice[spk] = assign_voice(spk)
        vid = speaker_to_voice[spk]
        label = spk or 'Narrator'
        print(f"▶ Segment {i}/{len(chunks)}: {label} ({vid})")
        audio = synthesize_text(txt, vid)
        audio.export(f"{base}_chunks/seg_{i:04d}.mp3", format="mp3")
        book += audio
        book.export(partial, format="mp3")

    book.export(out_mp3, format="mp3")
    print("Done! 🎧")

if __name__ == '__main__':
    main()
