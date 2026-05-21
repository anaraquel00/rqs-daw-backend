const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const upload = multer({ dest: 'uploads/' });

router.post('/process', upload.single('audio'), (req, res) => {
    try {
        console.log('[DSP ENGINE] Arquivo recebido. Acionando módulo Python...');
        
        const estilo = req.body.estilo || 'equilibrado';
        const intensidade = req.body.intensidade || 'media';
        const inputPath = req.file.path;
        const outputPath = path.join(__dirname, '../../uploads', `masterized_${req.file.filename}.wav`);
        const pythonScriptPath = path.join(__dirname, 'core_dsp.py');

       // O frontend envia req.body.preview = 'true' para testar, ou 'false' para masterizar a valer.
        const isPreview = req.body.preview === 'true' ? 'true' : 'false';

        const pythonProcess = spawn('./venv/bin/python3', [
    pythonScriptPath, 
    inputPath, 
    outputPath, 
    estilo, 
    intensidade,
    isPreview 
         ]);

        pythonProcess.stdout.on('data', (data) => {
            const output = data.toString().trim();
            if (output.startsWith('SUCESSO')) {
                const logs = output.split('|');
                console.log(`[DSP ENGINE] Masterização concluída. Ganho: ${logs[1]}dB`);
                
                // Retorna o arquivo de áudio final para o Front-End
                res.download(outputPath, 'rqs_master.wav', () => {
                    // Limpeza de cache tática: deleta os temporários após o envio
                    if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                    if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                });
            } else if (output.startsWith('ERRO')) {
                console.error(`[CRITICAL] Python Crash: ${output}`);
                res.status(500).json({ error: 'Falha no algoritmo Pedalboard' });
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            console.error(`[PYTHON LOG] ${data.toString()}`);
        });

    } catch (error) {
        console.error('[CRITICAL] Falha no roteador de DSP:', error);
        res.status(500).json({ error: 'Erro no roteamento interno' });
    }
});

module.exports = router;
