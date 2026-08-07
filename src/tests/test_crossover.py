import pytest
import numpy as np
from mastering_engine.dsp.crossover import LinkwitzRileyCrossover, CrossoverError


def test_invalid_parameters():
    """Garante que parâmetros incoerentes ou fisicamente impossíveis sejam rejeitados."""
    with pytest.raises(CrossoverError):
        LinkwitzRileyCrossover(sample_rate=-44100)
        
    with pytest.raises(CrossoverError):
        LinkwitzRileyCrossover(sample_rate=44100, low_hz=1000, high_hz=200)
        
    with pytest.raises(CrossoverError):
        LinkwitzRileyCrossover(sample_rate=44100, low_hz=200, high_hz=23000)


def test_perfect_reconstruction_null_test():
    """
    Testa se o crossover atinge a complementaridade perfeita.
    Ignoramos os transientes de borda inerentes ao sosfiltfilt nas primeiras 
    e últimas 500 amostras para focar na fidelidade da reconstrução em regime permanente.
    """
    fs = 44100
    crossover = LinkwitzRileyCrossover(sample_rate=fs, low_hz=200.0, high_hz=3000.0)
    
    # Criação de sinal de ruído branco estéreo de teste (completo em dinâmica e frequência)
    np.random.seed(42)
    t = np.linspace(0.0, 3.0, fs * 3, endpoint=False)
    noise = np.array([np.random.normal(0, 0.2, len(t)), np.random.normal(0, 0.2, len(t))], dtype=np.float32)
    
    # Dividir em bandas
    low, mid, high = crossover.split(noise)
    
    # Reconstruir o sinal
    reconstructed = crossover.sum_bands(low, mid, high)
    
    # Despreza as bordas (primeiras e últimas 500 amostras) para anular o efeito de transiente do filtfilt
    boundary_offset = 500
    difference = noise[:, boundary_offset:-boundary_offset] - reconstructed[:, boundary_offset:-boundary_offset]
    max_error = np.max(np.abs(difference))
    
    # No domínio prático float32 e regime estável, o erro deve ser infinitesimal (< 1e-5)
    assert max_error < 1e-5
    
    # Teste de correlação (deve ser praticamente 1.0 no regime estável)
    for ch in range(noise.shape[0]):
        correlation = np.corrcoef(noise[ch, boundary_offset:-boundary_offset], reconstructed[ch, boundary_offset:-boundary_offset])[0, 1]
        assert correlation == pytest.approx(1.0, abs=1e-6)


def test_band_energy_separation():
    """
    Valida se a filtragem está isolando as frequências corretas em cada banda.
    Ajustamos a asserção para respeitar o declive físico de 24 dB/oitava do LR4.
    """
    fs = 44100
    crossover = LinkwitzRileyCrossover(sample_rate=fs, low_hz=100.0, high_hz=5000.0)
    t = np.linspace(0.0, 1.0, fs, endpoint=False)
    
    # Onda senoidal de subgrave puro (50 Hz) - 1 oitava abaixo de 100 Hz
    sub_bass = np.array([np.sin(2 * np.pi * 50 * t)], dtype=np.float32)
    low, mid, high = crossover.split(sub_bass)
    
    # Calcula a potência de cada banda
    energy_low = np.sum(low**2)
    energy_mid = np.sum(mid**2)
    
    # Um filtro de 24 dB/oitava atenua a potência linear em ~251 vezes em uma oitava.
    # Usamos o limite de segurança de 150 vezes para passar no teste de forma robusta.
    assert energy_low > energy_mid * 150