import logging
import numpy as np
import scipy.signal as signal
import scipy.ndimage as ndimage

logger = logging.getLogger("mastering_engine.dsp.limiter")


class LimiterError(Exception):
    """Exceção para falhas no limitador de pico verdadeiro [14]."""
    pass


class TruePeakLimiter:
    """
    Limitador de Pico Verdadeiro Lookahead de fase linear e alta performance.
    Utiliza reamostragem polifásica 4x, filtros de máximo vetorizados em C e
    laço de salvaguarda de rebote de pico pós-decimação [8.3].
    """
    
    def __init__(self, sample_rate: int, ceiling_db: float = -1.0, lookahead_ms: float = 2.0, release_ms: float = 120.0):
        if sample_rate <= 0:
            raise LimiterError(f"Taxa de amostragem inválida: {sample_rate} Hz")
        if ceiling_db > 0.0:
            raise LimiterError(f"Ceiling deve ser menor ou igual a 0.0 dB (Valor atual: {ceiling_db} dB)")
            
        self.fs = sample_rate
        self.ceiling_db = ceiling_db
        self.ceiling_linear = 10 ** (ceiling_db / 20.0)
        
        self.lookahead_ms = lookahead_ms
        self.release_ms = release_ms
        self._design_release_filter()

    def _design_release_filter(self) -> None:
        """Projeta os filtros de suavização para a curva de release do limitador."""
        try:
            # Frequência de amostragem do domínio 4x
            fs_oversampled = self.fs * 4
            
            # Coeficiente de release
            g_release = np.exp(-1.0 / (fs_oversampled * (self.release_ms / 1000.0)))
            self.b_release = np.array([1.0 - g_release])
            self.a_release = np.array([1.0, -g_release])
            
        except Exception as e:
            raise LimiterError(f"Falha ao projetar filtros do limitador: {str(e)}")

    def process(self, audio: np.ndarray, threshold_db: float = 0.0) -> np.ndarray:
        """
        Executa a limitação de pico verdadeiro com lookahead vetorizado.
        Garante com precisão de ferro que o teto em dBTP seja respeitado.
        """
        if audio.shape[1] == 0:
            return audio.copy()
            
        try:
            audio_32 = audio.astype(np.float32, copy=False)
            
            # 1. Aplica Ganho de Entrada Inicial (Threshold de compressão)
            gain_input_linear = 10 ** (-threshold_db / 20.0)
            signal_amplified = audio_32 * gain_input_linear
            
            # 2. Reamostragem Polifásica de 4x (Domínio de Pico Verdadeiro)
            oversampling_factor = 4
            logger.debug(f"[Limiter] Iniciando sobreamostragem 4x de {audio_32.shape[1]} amostras.")
            
            # Filtro polifásico do SciPy projeta e aplica filtro Kaiser de fase linear estável
            audio_oversampled = np.zeros((audio_32.shape[0], audio_32.shape[1] * oversampling_factor), dtype=np.float32)
            for ch in range(audio_32.shape[0]):
                audio_oversampled[ch] = signal.resample_poly(signal_amplified[ch], oversampling_factor, 1)
                
            # 3. Lookahead Dinâmico Vetorizado por Canal
            # Tamanho da janela de lookahead no domínio 4x
            win_size = int((self.lookahead_ms / 1000.0) * (self.fs * oversampling_factor))
            if win_size % 2 == 0:
                win_size += 1
                
            delay = win_size // 2
            
            audio_limited_oversampled = np.zeros_like(audio_oversampled)
            
            for ch in range(audio_oversampled.shape[0]):
                ch_signal = audio_oversampled[ch]
                
                # Obtém o valor absoluto do sinal para rastrear picos
                abs_signal = np.abs(ch_signal)
                
                # Filtro de máximo deslizante vetorizado em C (Lookahead ultra-rápido!)
                # Origin configurada para escanear de forma antecipada (futuro)
                peaks = ndimage.maximum_filter1d(abs_signal, size=win_size, origin=-delay)
                
                # Suaviza a curva de picos com o filtro de release
                envelope = signal.filtfilt(self.b_release, self.a_release, peaks)
                
                # Garante proteção contra valores de envelope abaixo do teto linear
                envelope_safe = np.maximum(envelope, self.ceiling_linear)
                
                # Calcula a curva de ganho lookahead linear
                g_curve = self.ceiling_linear / envelope_safe
                
                # Aplica o atraso de compensação para sincronizar o ganho com o transiente atrasado
                ch_delayed = np.zeros_like(ch_signal)
                ch_delayed[delay:] = ch_signal[:-delay]
                
                audio_limited_oversampled[ch] = ch_delayed * g_curve
                
            # 4. Decimação de Volta para a Taxa Nativa
            audio_limited = np.zeros_like(audio_32)
            for ch in range(audio_32.shape[0]):
                audio_limited[ch] = signal.resample_poly(audio_limited_oversampled[ch], 1, oversampling_factor)
                
            # 5. Salvaguarda de Rebote de Pico Verdadeiro (SaaS Safe Loop)
            # Mede o True Peak do áudio decimado final antes da gravação em disco
            for ch in range(audio_limited.shape[0]):
                # Reamostra 4x apenas o canal decimado para calcular o True Peak real de saída
                reconstructed_tp = signal.resample_poly(audio_limited[ch], oversampling_factor, 1)
                max_tp_linear = np.max(np.abs(reconstructed_tp))
                
                if max_tp_linear > self.ceiling_linear:
                    # Se houver rebote, calcula o fator corretivo de segurança exato
                    correction_factor = self.ceiling_linear / max_tp_linear
                    logger.warning(
                        f"[Limiter] Rebote de decimação detectado no Canal {ch} (+{20*np.log10(max_tp_linear/self.ceiling_linear):.2f} dB). "
                        f"Aplicando fator de correção de pico verdadeiro: x{correction_factor:.3f}"
                    )
                    audio_limited[ch] = audio_limited[ch] * correction_factor
                    
            return audio_limited.astype(np.float32, copy=False)
            
        except Exception as e:
            logger.error(f"Erro catastrófico no processamento de limitação TP: {str(e)}", exc_info=True)
            raise LimiterError(f"Erro no processador de limitação: {str(e)}")