import soundfile as sf
import pyloudnorm as pyln
import numpy as np
from scipy.signal import resample_poly

TARGET_LUFS = -14.0
TRUE_PEAK_LIMIT = -1.0
OVERSAMPLE_FACTOR = 2

def oversample(sig, factor):
    if sig.ndim == 1:
        return resample_poly(sig, up=factor, down=1)
    return np.stack([resample_poly(sig[:, ch], up=factor, down=1)
                     for ch in range(sig.shape[1])], axis=1)

def fast_limiter(sig, limit_db=-1.0):
    limit = 10 ** (limit_db / 20)
    if sig.ndim == 1:
        max_val = np.max(np.abs(sig))
        if max_val > limit:
            sig = sig * (limit / max_val)
        return sig
    else:
        max_vals = np.max(np.abs(sig), axis=0)
        scaling = np.ones_like(max_vals)
        over = max_vals > limit
        scaling[over] = limit / max_vals[over]
        return sig * scaling

def enforce_lufs_and_peak(input_path: str, output_path: str):
    """
    Lê o áudio, ajusta para -14 LUFS cravado e aplica um True Peak Limiter seguro.
    """
    data, sr = sf.read(input_path)
    
    # 1. Medir a Loudness Original
    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(data)
    
    # 2. Normalizar matematicamente para -14 LUFS
    data_normalized = pyln.normalize.loudness(data, loudness, TARGET_LUFS)
    
    # 3. Proteção contra distorção (True Peak Limiter)
    data_ov = oversample(data_normalized, OVERSAMPLE_FACTOR)
    peak_db = 20 * np.log10(np.max(np.abs(data_ov)) + 1e-12)
    
    if peak_db > TRUE_PEAK_LIMIT:
        data_normalized = fast_limiter(data_normalized, TRUE_PEAK_LIMIT)
        
    # 4. Salva o arquivo final homologado
    sf.write(output_path, data_normalized, sr)
    
    # Retorna a nova medição para os logs do terminal
    new_loudness = meter.integrated_loudness(data_normalized)
    return round(new_loudness, 2)