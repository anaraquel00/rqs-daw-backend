import pytest
import numpy as np
import scipy.signal as signal
from mastering_engine.dsp.limiter import TruePeakLimiter, LimiterError


def test_invalid_parameters():
    """Valida rejeição de parâmetros incoerentes ou teto de decibéis positivo."""
    with pytest.raises(LimiterError):
        TruePeakLimiter(sample_rate=-44100)
        
    with pytest.raises(LimiterError):
        # Teto acima de 0.0 dBTP é rejeitado por segurança
        TruePeakLimiter(sample_rate=44100, ceiling_db=0.5)


def test_strict_true_peak_ceiling_enforcement():
    """
    Testa se o limitador blinda o sinal de saída contra picos que ultrapassem o teto.
    Injetamos um sinal de ruído caótico de altíssima energia com ganho de entrada (threshold) 
    agressivo e validamos se o pico verdadeiro do sinal decimado respeita estritamente o teto.
    """
    fs = 44100
    ceiling_db = -1.0
    limiter = TruePeakLimiter(sample_rate=fs, ceiling_db=ceiling_db, release_ms=50.0)
    
    np.random.seed(42)
    t = np.linspace(0.0, 1.0, fs, endpoint=False)
    # Sinal de ruído estéreo agressivo (com picos estourando a amplitude digital)
    bad_audio = np.array([np.random.normal(0, 1.5, len(t)), np.random.normal(0, 1.5, len(t))], dtype=np.float32)
    
    # Aplica limitação forçando 12 dB de ganho de entrada (compressão extrema)
    processed = limiter.process(bad_audio, threshold_db=-12.0)
    
    # Mede o True Peak real de saída do arquivo decimado final utilizando reamostragem polifásica 4x independente
    oversampling_factor = 4
    for ch in range(processed.shape[0]):
        upsampled = signal.resample_poly(processed[ch], oversampling_factor, 1)
        max_val_linear = np.max(np.abs(upsampled))
        max_tp_db = 20 * np.log10(max_val_linear) if max_val_linear > 1e-12 else -140.0
        
        # O pico verdadeiro final do arquivo de áudio decimado NUNCA deve ultrapassar o teto configurado
        assert max_tp_db <= ceiling_db + 1e-5


def test_limiter_bypass_on_null_input():
    """Valida se o limitador se comporta de forma neutra em sinais de silêncio absoluto."""
    fs = 44100
    limiter = TruePeakLimiter(sample_rate=fs, ceiling_db=-1.0)
    silence = np.zeros((2, fs), dtype=np.float32)
    
    processed = limiter.process(silence, threshold_db=0.0)
    
    assert np.max(np.abs(processed)) == 0.0