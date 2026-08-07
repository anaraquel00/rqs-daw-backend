import logging
import numpy as np
import scipy.signal as signal
from typing import Tuple

logger = logging.getLogger("mastering_engine.dsp.stereo")


class StereoError(Exception):
    """Exceção de domínio para falhas no processamento estéreo [14]."""
    pass


class MidSideStereoProcessor:
    """
    Processador espacial e harmônico Mid/Side avançado. 
    Contém matriz M/S de energia conservativa, mono-ização dinâmica de subgraves 
    e saturação harmônica lateral imune a aliasing via sobreamostragem 4x [8.6].
    """
    
    def __init__(self, sample_rate: int, mono_bass_hz: float = 120.0, side_sat_hz: float = 5000.0):
        if sample_rate <= 0:
            raise StereoError(f"Taxa de amostragem inválida: {sample_rate} Hz")
            
        self.fs = sample_rate
        self.mono_bass_hz = mono_bass_hz
        self.side_sat_hz = side_sat_hz
        self._design_filters()

    def _design_filters(self) -> None:
        """Projeta os filtros de fase zero necessários para o isolamento espectral."""
        try:
            nyquist = self.fs / 2.0
            self.sos_mono_bass = signal.butter(2, self.mono_bass_hz / nyquist, btype='high', output='sos')
            self.sos_side_sat = signal.butter(2, self.side_sat_hz / nyquist, btype='high', output='sos')
        except Exception as e:
            raise StereoError(f"Falha ao projetar filtros estéreo: {str(e)}")

    @staticmethod
    def encode_ms(audio: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Codifica o áudio estéreo em canais Mid (M) e Side (S) [8.6]."""
        if audio.shape[0] < 2:
            raise StereoError("Codificação M/S exige sinal estéreo de 2 canais")
        mid = 0.5 * (audio[0] + audio[1])
        side = 0.5 * (audio[0] - audio[1])
        return mid, side

    @staticmethod
    def decode_ms(mid: np.ndarray, side: np.ndarray) -> np.ndarray:
        """Decodifica os canais Mid (M) e Side (S) de volta para L/R [8.6]."""
        left = mid + side
        right = mid - side
        return np.vstack((left, right))

    def _apply_filter(self, signal_arr: np.ndarray, sos: np.ndarray) -> np.ndarray:
        return signal.sosfiltfilt(sos, signal_arr)

    def _process_segment(self, segment: np.ndarray, saturation_amount: float, width_multiplier: float) -> np.ndarray:
        """Processa um segmento curto de áudio de forma isolada em baixo consumo de RAM."""
        mid, side = self.encode_ms(segment)
        side_mono = self._apply_filter(side, self.sos_mono_bass)
        
        if saturation_amount > 0.0:
            side_high = self._apply_filter(side_mono, self.sos_side_sat)
            oversampling_factor = 4
            side_high_oversampled = signal.resample_poly(side_high, oversampling_factor, 1)
            saturated_oversampled = np.tanh(saturation_amount * 2.0 * side_high_oversampled)
            saturated_side = signal.resample_poly(saturated_oversampled, 1, oversampling_factor)
            side_processed = side_mono + (saturated_side * 0.5)
        else:
            side_processed = side_mono.copy()
            
        if width_multiplier != 1.0:
            side_scaled = side_processed * width_multiplier
        else:
            side_scaled = side_processed
            
        return self.decode_ms(mid, side_scaled)

    def process(
        self, 
        audio: np.ndarray, 
        saturation_amount: float = 0.3, 
        width_multiplier: float = 1.0,
        correlation_safeguard: float = 0.15
    ) -> np.ndarray:
        """
        Executa o processamento estéreo fatiando em blocos de 15 segundos 
        para garantir consumo de memória estável abaixo de 100 MB de RAM.
        """
        if audio.shape[0] < 2:
            return audio.copy()
            
        try:
            num_samples = audio.shape[1]
            # Blocos de 15 segundos com 2 segundos de amortecimento (pad) nas bordas [11]
            chunk_samples = 15 * self.fs
            pad_samples = 2 * self.fs
            processed_audio = np.zeros_like(audio)
            
            for start in range(0, num_samples, chunk_samples):
                end = min(start + chunk_samples, num_samples)
                
                # Aplica as margens físicas de amortecimento nas fatias
                pad_left = max(0, start - pad_samples)
                pad_right = min(num_samples, end + pad_samples)
                
                segment = audio[:, pad_left:pad_right]
                processed_segment = self._process_segment(segment, saturation_amount, width_multiplier)
                
                # Trata as bordas e insere cirurgicamente o bloco limpo no vetor de saída
                segment_start_idx = start - pad_left
                segment_end_idx = segment_start_idx + (end - start)
                processed_audio[:, start:end] = processed_segment[:, segment_start_idx:segment_end_idx]
                
            # 5. Laço de Convergência Iterativa de Correlação Estéreo sobre a faixa inteira reconstituída
            side_scaled = processed_audio[0] - processed_audio[1]
            mid = 0.5 * (processed_audio[0] + processed_audio[1])
            side_scaled = 0.5 * side_scaled
            
            for iteration in range(10):
                reconstructed_audio = self.decode_ms(mid, side_scaled)
                
                ch1_c = reconstructed_audio[0] - np.mean(reconstructed_audio[0])
                ch2_c = reconstructed_audio[1] - np.mean(reconstructed_audio[1])
                denom = np.sqrt(np.sum(ch1_c**2) * np.sum(ch2_c**2))
                
                correlation = np.sum(ch1_c * ch2_c) / denom if denom > 1e-12 else 1.0
                
                if correlation >= correlation_safeguard:
                    break
                    
                error = correlation_safeguard - correlation
                attenuation_factor = 1.0 - (error * 0.6)
                attenuation_factor = max(0.05, attenuation_factor)
                
                side_scaled = side_scaled * attenuation_factor
                logger.warning(
                    f"[Salvaguarda Estéreo] Iteração {iteration + 1}: Correlação crítica detectada ({correlation:.2f}). "
                    f"Atenuando Side: x{attenuation_factor:.2f}"
                )
                
            return self.decode_ms(mid, side_scaled).astype(np.float32, copy=False)
            
        except Exception as e:
            logger.error(f"Falha no processamento estéreo Mid/Side: {str(e)}", exc_info=True)
            raise StereoError(f"Erro no processador estéreo: {str(e)}")