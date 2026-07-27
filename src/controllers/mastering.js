const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// 🛡️ Ajustado para o diretório temporário obrigatório da AWS Lambda (/tmp)
const upload = multer({ dest: '/tmp/' });

router.post('/process', upload.single('audio'), (req, res) => {
    try {
        console.log('[DSP ENGINE] Arquivo recebido. Acionando módulo Python...');
        
        if (!req.file) {
            return res.status(400).json({ error: 'Nenhum arquivo de áudio enviado.' });
        }

        const estilo = req.body.estilo || 'equilibrado';
        const intensidade = req.body.intensidade || 'media';
        const inputPath = req.file.path;
        
        // 🛡️ Salvando o arquivo de saída também em /tmp/ para evitar erro de permissão na AWS
        const outputPath = path.join('/tmp', `masterized_${req.file.filename}.wav`);
        const pythonScriptPath = path.join(__dirname, 'core_dsp.py');

        const isPreview = req.body.preview === 'true' ? 'true' : 'false';

        // Na AWS Lambda / Docker, usamos python3 direto
        const pythonCommand = 'python3';

        const pythonProcess = spawn(pythonCommand, [
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
                
                res.download(outputPath, 'rqs_master.wav', () => {
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
