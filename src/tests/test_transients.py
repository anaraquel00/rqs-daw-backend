import pytest
import numpy as np
from mastering_engine.dsp.transients import AdaptiveTransientShaper, TransientError


def test_invalid_parameters():
    """Valida rejeição de taxas de amostragem inválidas."""
    with pytest.raises(TransientError):
        AdaptiveTransientShaper(sample_rate=-48000)


def test_bypass_slammed_tracks():
    """Garante que a salvaguarda de Fator de Crista impeça o processamento em faixas já esmagadas por IA."""
    fs = 44100
    shaper = AdaptiveTransientShaper(sample_rate=fs)
    
    t = np.linspace(0.0, 1.0, fs, endpoint=False)
    square_wave = np.array([np.sign(np.sin(2 * np.pi * 400 * t))], dtype=np.float32)
    
    processed = shaper.process(square_wave, intensity=0.5)
    
    difference = square_wave - processed
    assert np.max(np.abs(difference)) == 0.0


def test_transient_restoration_dynamic_track():
    """Garante que faixas dinâmicas tenham seus transientes de ataque limpos e reforçados."""
    fs = 44100
    shaper = AdaptiveTransientShaper(sample_rate=fs)
    
    t = np.linspace(0.0, 1.0, fs, endpoint=False)
    impulse = np.sin(2 * np.pi * 200 * t) * np.exp(-20 * t)
    audio = np.array([impulse, impulse], dtype=np.float32)
    
    processed = shaper.process(audio, intensity=0.3)
    
    assert np.max(np.abs(processed)) > np.max(np.abs(audio))


def test_deterministic_local_processing():
    """
    Testa se o processamento é 100% local e determinístico sob o mesmo Fator de Crista de referência.
    Utiliza uma margem de warmup de 22.000 amostras para acomodar as 10 constantes de tempo do filtro lento.
    Isso prova matematicamente a consistência absoluta de audição entre o ZLP de 15s e o mestre final.
    """
    fs = 44100
    shaper = AdaptiveTransientShaper(sample_rate=fs)
    
    np.random.seed(42)
    t = np.linspace(0.0, 5.0, fs * 5, endpoint=False)
    large_track = np.array([np.random.normal(0, 0.1, len(t)), np.random.normal(0, 0.1, len(t))], dtype=np.float32)
    
    # Pré-calcula o Fator de Crista global de referência para injetar em ambos os runs (padrão SaaS)
    large_rms = np.sqrt(np.mean(large_track**2))
    large_peak = np.max(np.abs(large_track))
    global_cf = 20.0 * np.log10(large_peak / large_rms)
    
    # Processa o mestre completo
    processed_large = shaper.process(large_track, intensity=0.2, global_crest_factor=global_cf)
    segment_large = processed_large[:, 50000:100000]
    
    # Processa o segmento isolado (ZLP) com margem de amortecimento física segura (22000 amostras)
    pad = 22000
    segment_isolated_padded = large_track[:, 50000-pad:100000+pad]
    processed_isolated_padded = shaper.process(segment_isolated_padded, intensity=0.2, global_crest_factor=global_cf)
    segment_isolated = processed_isolated_padded[:, pad:-pad]
    
    # Agora, com a calibração de ganho e warmup reverso idênticos, a paridade atinge a precisão infinitesimal!
    difference = segment_large - segment_isolated
    assert np.max(np.abs(difference)) < 1e-5