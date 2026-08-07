import logging
import numpy as np
import scipy.signal as signal
from typing import Optional

logger = logging.getLogger("mastering_engine.dsp.transients")


class TransientError(Exception):
    """Exceção para falhas no processamento dinâmico de transientes [14]."""
    pass


class AdaptiveTransientShaper:
    """
    Modelador de transientes local e adaptativo. 
    Rastreia frentes de ataque utilizando envelopes IIR de fase zero complementares. 
    Aplica salvaguarda adaptativa por Fator de Crista para evitar distorção digital [8.8].
    """
    
    def __init__(self, sample_rate: int, fast_tau: float = 0.004, slow_tau: float = 0.050):
        if sample_rate <= 0:
            raise TransientError(f"Taxa de amostragem inválida: {sample_rate} Hz")
            
        self.fs = sample_rate
        self.fast_tau = fast_tau
        self.slow_tau = slow_tau
        self._design_smoothing_filters()

    def _design_smoothing_filters(self) -> None:
        """Calcula os coeficientes IIR de 1ª ordem para rastreamento de envelope."""
        try:
            # Coeficiente rápido (Ataque - ~4ms)
            g_fast = np.exp(-1.0 / (self.fs * self.fast_tau))
            self.b_fast = np.array([1.0 - g_fast])
            self.a_fast = np.array([1.0, -g_fast])
            
            # Coeficiente lento (Sustentação - ~50ms)
            g_slow = np.exp(-1.0 / (self.fs * self.slow_tau))
            self.b_slow = np.array([1.0 - g_slow])
            self.a_slow = np.array([1.0, -g_slow])
            
            # Coeficiente de decaimento pós-ataque para suavizar ganho (~3ms)
            g_decay = np.exp(-1.0 / (self.fs * 0.003))
            self.b_decay = np.array([1.0 - g_decay])
            self.a_decay = np.array([1.0, -g_decay])
            
        except Exception as e:
            raise TransientError(f"Falha ao projetar filtros de envelope: {str(e)}")

    def _apply_smoothing(self, abs_signal: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
        """Aplica filtragem de fase zero bidirecional para alinhamento temporal perfeito."""
        return signal.filtfilt(b, a, abs_signal, axis=-1)

    def process(self, audio: np.ndarray, intensity: float = 0.2, global_crest_factor: Optional[float] = None) -> np.ndarray:
        """
        Executa a modelagem de transientes adaptativa localmente.
        Permite receber o Fator de Crista global pré-calculado para garantir paridade absoluta [8.8].
        """
        if intensity <= 0.0:
            return audio.copy()
            
        try:
            audio_32 = audio.astype(np.float32, copy=False)
            
            # 1. Determinação do Fator de Crista (pré-calculado para SaaS ou local para standalone)
            if global_crest_factor is not None:
                crest_factor_db = global_crest_factor
            else:
                rms = np.sqrt(np.mean(audio_32**2))
                peak = np.max(np.abs(audio_32))
                if rms > 1e-12:
                    crest_factor_db = 20.0 * np.log10(peak / rms)
                else:
                    crest_factor_db = 12.0  # Default seguro para silêncio
                
            # Escala de proteção contínua: bypass se CF < 6dB, completo se CF > 10dB
            if crest_factor_db <= 6.0:
                logger.warning(
                    f"[Salvaguarda de Transientes] Faixa ultra-comprimida/saturada (Fator de Crista: {crest_factor_db:.2f} dB). "
                    "Bypass preventivo ativado para evitar distorção harmônica."
                )
                return audio.copy()
            elif crest_factor_db < 10.0:
                scale = (crest_factor_db - 6.0) / 4.0
                logger.info(
                    f"[Salvaguarda de Transientes] Faixa com dinâmica reduzida (Fator de Crista: {crest_factor_db:.2f} dB). "
                    f"Atenuando intensidade de restauração para {scale * 100:.1f}%."
                )
            else:
                scale = 1.0
                
            effective_intensity = intensity * scale
            
            # 2. Obtenção do valor absoluto para detecção de energia
            abs_signal = np.abs(audio_32)
            
            # 3. Rastreamento de Envelopes com alinhamento de fase linear
            env_fast = self._apply_smoothing(abs_signal, self.b_fast, self.a_fast)
            env_slow = self._apply_smoothing(abs_signal, self.b_slow, self.a_slow)
            
            # 4. Cálculo da Relação Dinâmica (Transient Ratio)
            epsilon = 1e-5
            ratio = env_fast / (env_slow + epsilon)
            
            # Isola frentes de ataque
            transients = np.maximum(0.0, ratio - 1.0)
            
            # Suaviza a curva de transientes resultante para impedir cliques e estalos digitais
            transients_smoothed = self._apply_smoothing(transients, self.b_decay, self.a_decay)
            
            # 5. Aplicação do Ganho Local
            gain_curve = 1.0 + effective_intensity * transients_smoothed
            
            return (audio_32 * gain_curve).astype(np.float32, copy=False)
            
        except Exception as e:
            logger.error(f"Falha ao modelar transientes de áudio: {str(e)}", exc_info=True)
            raise TransientError(f"Erro no modelador de transientes: {str(e)}")