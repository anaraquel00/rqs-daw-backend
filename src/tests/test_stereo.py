import pytest
import numpy as np
from mastering_engine.dsp.stereo import MidSideStereoProcessor, StereoError


def test_perfect_ms_reconstruction_bypass():
    """Garante que a codificação/decodificação M/S direta (sem processamento) seja perfeitamente complementar."""
    fs = 44100
    processor = MidSideStereoProcessor(sample_rate=fs)
    
    np.random.seed(42)
    t = np.linspace(0.0, 1.0, fs, endpoint=False)
    audio = np.array([np.random.normal(0, 0.2, len(t)), np.random.normal(0, 0.2, len(t))], dtype=np.float32)
    
    # Entra e sai da matriz Mid/Side
    mid, side = processor.encode_ms(audio)
    reconstructed = processor.decode_ms(mid, side)
    
    difference = audio - reconstructed
    assert np.max(np.abs(difference)) < 1e-6


def test_mono_bass_functionality():
    """Valida se o Mono Bass limpa completamente qualquer conteúdo de graves do canal Side."""
    fs = 44100
    mono_bass_freq = 120.0
    processor = MidSideStereoProcessor(sample_rate=fs, mono_bass_hz=mono_bass_freq)
    
    t = np.linspace(0.0, 1.0, fs, endpoint=False)
    # Sinal de subgrave em antifase extrema em 50 Hz (1 oitava abaixo do corte de 120 Hz)
    sub_bass_antifase = np.array([np.sin(2 * np.pi * 50 * t), -np.sin(2 * np.pi * 50 * t)], dtype=np.float32)
    
    # Processa o sinal estéreo
    processed = processor.process(sub_bass_antifase, saturation_amount=0.0, width_multiplier=1.0)
    
    # Converte o processado para Mid/Side para validar
    mid, side = processor.encode_ms(processed)
    
    # Despreza o transiente de inicialização do filtro de fase zero (primeiras 1000 amostras)
    boundary_offset = 1000
    side_steady = side[boundary_offset:-boundary_offset]
    
    # No regime permanente, a energia do subgrave lateral deve estar drasticamente limpa (< 0.02)
    assert np.max(np.abs(side_steady)) < 2e-2


def test_correlation_safeguard():
    """Verifica se o limite de segurança impede o sinal de ter correlação estéreo negativa extrema."""
    fs = 44100
    processor = MidSideStereoProcessor(sample_rate=fs)
    
    # Geramos ruído estéreo parcialmente correlacionado com correlação inicial muito negativa (campo muito aberto)
    np.random.seed(42)
    mid_noise = np.random.normal(0, 0.2, fs)
    side_noise = np.random.normal(0, 1.0, fs)  # Side muito mais forte que o Mid
    
    left = mid_noise + side_noise
    right = mid_noise - side_noise
    bad_stereo = np.vstack((left, right)).astype(np.float32)
    
    # Solicita uma abertura estéreo exagerada (largura x 2.0) que derrubaria a correlação
    processed = processor.process(bad_stereo, saturation_amount=0.0, width_multiplier=2.0, correlation_safeguard=0.15)
    
    # Mede a correlação do sinal resultante
    ch1_c = processed[0] - np.mean(processed[0])
    ch2_c = processed[1] - np.mean(processed[1])
    denom = np.sqrt(np.sum(ch1_c**2) * np.sum(ch2_c**2))
    correlation = np.sum(ch1_c * ch2_c) / denom if denom > 1e-12 else 1.0
    
    # A salvaguarda deve ter agido de forma contínua, puxando a correlação para acima de 0.15
    assert correlation >= 0.15 - 1e-3