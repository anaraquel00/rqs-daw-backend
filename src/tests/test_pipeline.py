import os
import pytest
import numpy as np
import soundfile as sf
from mastering_engine.pipeline.mastering import MasteringPipeline


def test_complete_mastering_pipeline_end_to_end(tmp_path):
    """
    Testa a orquestração completa do pipeline híbrido de ponta a ponta.
    Verifica se o relatório JSON de saída contém todas as assinaturas técnicas exigidas.
    """
    fs = 44100
    # Cria caminhos temporários isolados para simular o upload e render no /tmp [5.2]
    input_wav = os.path.join(tmp_path, "input_test.wav")
    output_wav = os.path.join(tmp_path, "output_mastered.wav")
    
    # Cria arquivo WAV estéreo dinâmico de 3 segundos para teste
    np.random.seed(42)
    t = np.linspace(0.0, 3.0, fs * 3, endpoint=False)
    test_audio = np.array([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 220 * t)], dtype=np.float32).T
    sf.write(input_wav, test_audio, fs, subtype="PCM_24")
    
    # Instancia o pipeline com o ID de tarefa simulado
    pipeline = MasteringPipeline(task_id="test_e2e_job", profile_name="thunder")
    
    # Executa a masterização completa solicitando meta customizada
    report = pipeline.masterize(
        input_path=input_wav,
        output_path=output_wav,
        is_preview=False,
        custom_overrides={"target_lufs": -12.0}  # Requisita limite customizado do Angular
    )
    
    # --- Asserções do Relatório JSON de Produção [9] ---
    assert report["task_id"] == "test_e2e_job"
    assert report["status"] == "completed"
    assert report["is_preview"] is False
    assert "input" in report
    assert "output" in report
    assert "validation" in report
    assert "warnings" in report
    
    # Verifica se as metas de decisões dinâmicas foram mapeadas no JSON
    assert report["decisions"]["profile"] == "thunder"
    assert report["decisions"]["target_lufs"] == -12.0
    
    # Verifica se o arquivo mestre consolidado foi gravado fisicamente no disco
    assert os.path.exists(output_wav)
    
    # Lê o arquivo gravado e valida integridade física de áudio e teto dBTP
    out_audio, out_sr = sf.read(output_wav)
    assert out_sr == fs
    assert np.max(np.abs(out_audio)) <= 1.0  # Sem distorção por clipping de amostra digital