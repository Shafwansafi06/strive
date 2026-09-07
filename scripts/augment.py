"""Explicit OFFLINE evaluation preprocessing; not part of live audio retention."""
import argparse
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from strive.audio import decode, RATE


def main():
    p = argparse.ArgumentParser()
    p.add_argument('source'); p.add_argument('output')
    p.add_argument('--codec', choices=['g711','opus','narrowband'], default='g711')
    p.add_argument('--noise-snr-db', type=float)
    p.add_argument('--packet-loss', type=float, default=0)
    p.add_argument('--seed', type=int, default=26104)
    a = p.parse_args()
    if not 0 <= a.packet_loss < 1: raise SystemExit('packet-loss must be in [0,1)')
    x = decode(Path(a.source).read_bytes())
    if a.codec == 'g711':
        options = ['-ar','8000','-c:a','pcm_mulaw','-f','mulaw']
        input_options = ['-f','mulaw','-ar','8000','-ac','1']
    elif a.codec == 'opus':
        options = ['-c:a','libopus','-b:a','16k','-f','ogg']
        input_options = ['-f','ogg']
    else:
        options = ['-ar','8000','-f','s16le']; input_options = ['-f','s16le','-ar','8000','-ac','1']
    encoded = subprocess.run(['ffmpeg','-v','error','-f','f32le','-ar',str(RATE),'-ac','1','-i','pipe:0',*options,'pipe:1'], input=x.astype('<f4').tobytes(), capture_output=True, check=True, timeout=30)
    decoded = subprocess.run(['ffmpeg','-v','error',*input_options,'-i','pipe:0','-ar',str(RATE),'-ac','1','-f','f32le','pipe:1'], input=encoded.stdout, capture_output=True, check=True, timeout=30)
    x = np.frombuffer(decoded.stdout, dtype='<f4').copy()
    rng = np.random.default_rng(a.seed)
    if a.noise_snr_db is not None:
        noise_scale = np.sqrt(np.mean(x*x)) / (10 ** (a.noise_snr_db / 20))
        x += rng.normal(0, noise_scale, len(x))
    for start in range(0, len(x), 320):
        if rng.random() < a.packet_loss: x[start:start+320] = 0
    output = Path(a.output); output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, np.clip(x,-1,1), RATE, subtype='PCM_16')
    print('Wrote explicit offline evaluation artifact:', output)
    print('Keep its source_id and speaker_id identical to the original to prevent split leakage.')


if __name__ == '__main__': main()
