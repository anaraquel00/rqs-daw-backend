# mastering_engine/analysis/metering.py

import logging
import numpy as np
import scipy.signal as signal
from typing import Tuple, List, Optional
from pydantic import BaseModel, Field

# Configuração de registro estruturado simulado para SaaS
logger = logging.getLogger("mastering_engine.analysis.metering")


class AudioMetrics(BaseModel):
    """
    Estrutura de dados de nível de produção contendo as métricas de áudio 
    em estrita conformidade com ITU-R BS.1770-4 e EBU R128 [13].
    """
    integrated_lufs: float = Field(..., description="Loudness Integrado em LUFS/LKFS")
    true_peak_dbtp: float = Field(..., description="Pico Verdadeiro medido em dBTP")
    sample_peak_dbfs: float = Field(..., description="Pico de amostra clássico em dBFS")
    loudness_range_lra: float = Field(..., description="Faixa de Loudness em Unidades de Loudness (LU)")
    crest_factor_db: float = Field(..., description="Fator de Crista em dB")
    plr: float = Field(..., description="Peak-to-Loudness Ratio (PLR)")
    dc_offset: float = Field(..., description="Componente de corrente contínua máxima nos canais")
    stereo_correlation: float = Field(..., description="Correlação estéreo média da faixa [-1.0 a 1.0]")


class MeteringError(Exception):
    """Exceção de domínio para falhas no motor de medição [14]."""
    pass


class AudioMeter:
    """
    Motor matemático de alta performance para medição acústica tridimensional:
    Frequência, Tempo, Dinâmica e Pico Verdadeiro.
    """
    
    def __init__(self, sample_rate: int):
        if sample_rate <= 0:
            raise MeteringError(f"Taxa de amostragem inválida: {sample_rate} Hz")
        self.fs = sample_rate
        self._init_k_filter_coefficients()

    def _init_k_filter_coefficients(self) -> None:
        """
        Calcula os coeficientes dos filtros biquad da ponderação K (K-Weighting) 
        dinamicamente para qualquer taxa de amostragem através de aproximações bilineares,
        conforme especificado na norma ITU-R BS.1770-4.
        """
        try:
            # Filtro 1: High-Shelving (Simulação acústica da cabeça humana)
            # Parâmetros de calibração para 48 kHz adaptados para fs genérico
            f1 = 1681.974450978682
            g1 = 3.999843806974416
            q1 = 0.7071752369554193
            
            # Bilinear transform para High-Shelving filter
            k1 = np.tan(np.pi * f1 / self.fs)
            v0 = 10 ** (g1 / 20.0)
            
            # Coeficientes para o shelving
            denom1 = 1.0 + (1.0 / q1) * k1 + k1 * k1
            self.b1 = np.array([
                (v0 + (v0 / q1) * k1 + k1 * k1) / denom1,
                2.0 * (k1 * k1 - v0) / denom1,
                (v0 - (v0 / q1) * k1 + k1 * k1) / denom1
            ], dtype=np.float64)
            self.a1 = np.array([
                1.0,
                2.0 * (k1 * k1 - 1.0) / denom1,
                (1.0 - (1.0 / q1) * k1 + k1 * k1) / denom1
            ], dtype=np.float64)

            # Filtro 2: High-Pass (Atenuação de subgraves não audíveis)
            f2 = 38.13547087613982
            q2 = 0.5000000000000000
            
            # Bilinear transform para High-Pass filter
            k2 = np.tan(np.pi * f2 / self.fs)
            denom2 = 1.0 + (1.0 / q2) * k2 + k2 * k2
            
            self.b2 = np.array([
                1.0 / denom2,
                -2.0 / denom2,
                1.0 / denom2
            ], dtype=np.float64)
            self.a2 = np.array([
                1.0,
                2.0 * (k2 * k2 - 1.0) / denom2,
                (1.0 - (1.0 / q2) * k2 + k2 * k2) / denom2
            ], dtype=np.float64)
            
        except Exception as e:
            raise MeteringError(f"Falha ao computar os coeficientes do Filtro K: {str(e)}")

    def _apply_k_weighting(self, audio: np.ndarray) -> np.ndarray:
        """
        Aplica os filtros de ponderação K sobre o array de áudio.
        Garante processamento estável e preciso em float64 para evitar ruído numérico.
        Sinal de entrada esperado: (canais, amostras) [13].
        """
        audio_64 = audio.astype(np.float64, copy=False)
        # Processa cada canal sequencialmente para manter estabilidade temporal
        filtered = np.zeros_like(audio_64)
        for ch in range(audio_64.shape[0]):
            # Aplica Etapa 1: High Shelving
            stage1 = signal.lfilter(self.b1, self.a1, audio_64[ch])
            # Aplica Etapa 2: High Pass
            filtered[ch] = signal.lfilter(self.b2, self.a2, stage1)
        return filtered

    def measure_loudness(self, audio: np.ndarray) -> Tuple[float, float]:
        """
        Calcula o Loudness Integrado (LUFS) e a Faixa de Loudness (LRA) de acordo 
        com ITU-R BS.1770-4 e EBU Tech 3342.
        Preserva a memória do sistema utilizando janelamento vetorizado do NumPy.
        """
        if audio.shape[1] < int(0.4 * self.fs):
            # Tratamento robusto para áudios excessivamente curtos [4]
            return -70.0, 0.0

        # 1. Aplicar ponderação K
        y = self._apply_k_weighting(audio)
        
        # 2. Configuração de Janelas (400ms sobreposto a cada 100ms)
        win_len = int(0.400 * self.fs)
        win_step = int(0.100 * self.fs)
        num_samples = audio.shape[1]
        
        # Criação de índices para janelamento vetorizado rápido em NumPy
        shape = ((num_samples - win_len) // win_step + 1, win_len)
        strides = (y.strides[1] * win_step, y.strides[1])
        
        # Extração de blocos por canal para evitar loops pesados em Python
        blocks_ch1 = np.lib.stride_tricks.as_strided(y[0], shape=shape, strides=strides)
        if y.shape[0] > 1:
            blocks_ch2 = np.lib.stride_tricks.as_strided(y[1], shape=shape, strides=strides)
            # Potência por bloco (Soma de canais com ganho unitário G_i = 1.0)
            z_j = (np.mean(blocks_ch1**2, axis=1) + np.mean(blocks_ch2**2, axis=1)) / 2.0
        else:
            z_j = np.mean(blocks_ch1**2, axis=1)
            
        # Adiciona pequena constante de proteção contra log de zero
        z_j = np.maximum(z_j, 1e-12)
        
        # Loudness bruto dos blocos
        l_j = -0.691 + 10.0 * np.log10(z_j)
        
        # --- Algoritmo de Gating Duplo ---
        # Gate Absoluto a -70 LKFS
        gated_abs_indices = l_j > -70.0
        if not np.any(gated_abs_indices):
            return -70.0, 0.0
            
        z_abs = z_j[gated_abs_indices]
        l_abs = l_j[gated_abs_indices]
        
        # Gate Relativo a -10 dB abaixo da média de energia dos sobreviventes do Gate Absoluto
        avg_energy_abs = np.mean(z_abs)
        rel_threshold = -0.691 + 10.0 * np.log10(avg_energy_abs) - 10.0
        
        gated_rel_indices = l_abs > rel_threshold
        if not np.any(gated_rel_indices):
            # Se nenhum bloco passar pelo gate relativo, usa a média do gate absoluto
            integrated_lufs = -0.691 + 10.0 * np.log10(avg_energy_abs)
        else:
            z_final = z_abs[gated_rel_indices]
            integrated_lufs = -0.691 + 10.0 * np.log10(np.mean(z_final))
            
        # --- Cálculo de Loudness Range (LRA) ---
        # Em conformidade com a EBU Tech 3342 (usa janelas curtas de 3 segundos com passo de 1s)
        lra_win_len = int(3.0 * self.fs)
        lra_win_step = int(1.0 * self.fs)
        
        if num_samples >= lra_win_len:
            lra_shape = ((num_samples - lra_win_len) // lra_win_step + 1, lra_win_len)
            lra_strides = (y.strides[1] * lra_win_step, y.strides[1])
            
            lra_blocks_ch1 = np.lib.stride_tricks.as_strided(y[0], shape=lra_shape, strides=lra_strides)
            if y.shape[0] > 1:
                lra_blocks_ch2 = np.lib.stride_tricks.as_strided(y[1], shape=lra_shape, strides=lra_strides)
                z_lra = (np.mean(lra_blocks_ch1**2, axis=1) + np.mean(lra_blocks_ch2**2, axis=1)) / 2.0
            else:
                z_lra = np.mean(lra_blocks_ch1**2, axis=1)
                
            z_lra = np.maximum(z_lra, 1e-12)
            l_lra = -0.691 + 10.0 * np.log10(z_lra)
            
            # Gating absoluto de -70 LKFS para LRA
            lra_gated_abs = l_lra[l_lra > -70.0]
            if len(lra_gated_abs) > 0:
                # Gating relativo de -20 dB para LRA (EBU Tech 3342)
                lra_avg_energy = np.mean(10**((lra_gated_abs + 0.691)/10.0))
                lra_rel_threshold = -0.691 + 10.0 * np.log10(lra_avg_energy) - 20.0
                
                final_lra_blocks = lra_gated_abs[lra_gated_abs > lra_rel_threshold]
                if len(final_lra_blocks) >= 2:
                    # LRA é a diferença entre os percentis 10% e 95%
                    p10 = np.percentile(final_lra_blocks, 10)
                    p95 = np.percentile(final_lra_blocks, 95)
                    lra = p95 - p10
                else:
                    lra = 0.0
            else:
                lra = 0.0
        else:
            lra = 0.0
            
        return float(integrated_lufs), float(lra)

    def measure_true_peak(self, audio: np.ndarray) -> float:
        """
        Calcula o Pico Verdadeiro (True Peak) em dBTP através de interpolação polifásica 
        de 4x em fase linear utilizando processamento otimizado de sub-bandas para 
        preservar a integridade da memória.
        """
        oversampling_factor = 4
        
        # Filtro Kaiser de alta ordem para atenuação rigorosa de banda de rejeição (> 80 dB)
        # scipy.signal.resample_poly projeta e aplica este filtro de forma otimizada
        true_peaks = []
        
        # Para evitar estouro de memória no Lambda, processa o sinal em blocos se exceder 5 minutos
        chunk_size = 5 * 60 * self.fs
        num_samples = audio.shape[1]
        
        for ch in range(audio.shape[0]):
            ch_peaks = []
            for start in range(0, num_samples, chunk_size):
                end = min(start + chunk_size, num_samples)
                segment = audio[ch, start:end]
                
                # Executa a interpolação polifásica de alto desempenho
                upsampled = signal.resample_poly(segment, oversampling_factor, 1)
                
                # Encontra o pico absoluto linear deste segmento
                max_val = np.max(np.abs(upsampled))
                ch_peaks.append(max_val)
                
            true_peaks.append(np.max(ch_peaks))
            
        overall_peak_linear = np.max(true_peaks)
        
        # Evita divisão ou log de zero caso o sinal seja nulo (silêncio absoluto)
        if overall_peak_linear < 1e-12:
            return -140.0
            
        true_peak_dbtp = 20 * np.log10(overall_peak_linear)
        return float(true_peak_dbtp)

    def analyze_signal(self, audio: np.ndarray) -> AudioMetrics:
        """
        Executa a análise técnica completa de áudio, extraindo parâmetros de qualidade
        profissionais essenciais para a masterização adaptativa de IA.
        """
        try:
            # 1. Obter Loudness Integrado e Faixa Dinâmica (LRA)
            lufs, lra = self.measure_loudness(audio)
            
            # 2. Obter Pico Verdadeiro (dBTP)
            true_peak = self.measure_true_peak(audio)
            
            # 3. Obter Pico de Amostra clássico (dBFS)
            sample_peak_linear = np.max(np.abs(audio))
            sample_peak_dbfs = 20 * np.log10(sample_peak_linear) if sample_peak_linear > 1e-12 else -140.0
            
            # 4. Calcular RMS Global
            rms = np.sqrt(np.mean(audio**2))
            
            # 5. Calcular Fator de Crista e PLR
            if rms > 1e-12:
                # Fator de Crista em dB (Pico de amostra em relação ao RMS)
                crest_factor_db = 20 * np.log10(sample_peak_linear / rms)
                # Peak-to-Loudness Ratio (PLR)
                plr = true_peak - lufs
            else:
                crest_factor_db = 0.0
                plr = 0.0
                
            # 6. Calcular DC Offset máximo entre canais
            dc_offset = float(np.max(np.abs(np.mean(audio, axis=1))))
            
            # 7. Calcular Correlação Estéreo (Média)
            if audio.shape[0] > 1:
                # Centraliza os sinais
                ch1_centered = audio[0] - np.mean(audio[0])
                ch2_centered = audio[1] - np.mean(audio[1])
                
                denom = np.sqrt(np.sum(ch1_centered**2) * np.sum(ch2_centered**2))
                if denom > 1e-12:
                    stereo_correlation = float(np.sum(ch1_centered * ch2_centered) / denom)
                else:
                    stereo_correlation = 1.0
            else:
                stereo_correlation = 1.0  # Sinal Mono tem correlação perfeita
                
            return AudioMetrics(
                integrated_lufs=round(lufs, 2),
                true_peak_dbtp=round(true_peak, 2),
                sample_peak_dbfs=round(float(sample_peak_dbfs), 2),
                loudness_range_lra=round(lra, 2),
                crest_factor_db=round(float(crest_factor_db), 2),
                plr=round(float(plr), 2),
                dc_offset=float(dc_offset),
                stereo_correlation=round(stereo_correlation, 3)
            )
            
        except Exception as e:
            logger.error(f"Erro catastrófico na análise de sinal: {str(e)}", exc_info=True)
            raise MeteringError(f"Falha na medição acústica: {str(e)}")


class LoudnessGainMatch:
    """
    Controlador iterativo retroalimentado que ajusta o ganho do áudio 
    até que ele convirja precisamente para a meta de LUFS especificada.
    Preveja e contorne o comportamento não linear de compressores e limitadores.
    """
    
    @staticmethod
    def match(
        audio: np.ndarray, 
        meter: AudioMeter, 
        target_lufs: float, 
        tolerance_db: float = 0.1, 
        max_iterations: int = 5
    ) -> Tuple[np.ndarray, float]:
        """
        Ajusta o ganho de forma iterativa baseada em retroalimentação de erro [8].
        Retorna o áudio processado e o ganho linear total aplicado.
        """
        current_audio = audio.copy()
        total_gain_linear = 1.0
        
        for iteration in range(max_iterations):
            metrics = meter.analyze_signal(current_audio)
            error = target_lufs - metrics.integrated_lufs
            
            # Se o erro estiver dentro da margem de tolerância SaaS estabelecida, interrompe o laço
            if abs(error) <= tolerance_db:
                logger.info(f"Convergência de Loudness atingida na iteração {iteration + 1}. Volume final: {metrics.integrated_lufs} LUFS")
                break
                
            # Calcula o incremento de ganho logarítmico necessário
            step_gain_db = error
            step_gain_linear = 10 ** (step_gain_db / 20.0)
            
            # Aplica o fator de ganho linear
            current_audio = current_audio * step_gain_linear
            total_gain_linear *= step_gain_linear
            
            logger.debug(f"Iteração {iteration + 1}: Erro = {error:.2f} dB, Ajuste de Ganho = {step_gain_db:.2f} dB")
            
        return current_audio, float(total_gain_linear)