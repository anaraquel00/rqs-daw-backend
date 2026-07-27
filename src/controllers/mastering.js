const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// 🛡️ Armazena o arquivo temporariamente na RAM para evitar falhas de disco no Lambda
const upload = multer({ storage: multer.memoryStorage() });

router.post('/process', upload.any(), (req, res) => {
    try {
        console.log('[DSP ENGINE] Requisição HTTP recebida na AWS Lambda.');
        
        const uploadedFile = req.files && req.files.length > 0 ? req.files[0] : null;

        if (!uploadedFile) {
            console.error('[CRITICAL] Nenhum arquivo binário encontrado no payload.');
            return res.status(400).json({ error: 'Nenhum arquivo de áudio enviado.' });
        }

        // Gravando o buffer da memória com segurança total no diretório /tmp da AWS
        const inputPath = path.join('/tmp', `input_${Date.now()}.wav`);
        fs.writeFileSync(inputPath, uploadedFile.buffer);

        const estilo = req.body.estilo || 'equilibrado';
        const intensidade = req.body.intensidade || 'media';
        const outputPath = path.join('/tmp', `output_${Date.now()}.wav`);
        const pythonScriptPath = path.join(__dirname, 'core_dsp.py');
        const isPreview = req.body.preview === 'true' ? 'true' : 'false';

        console.log(`[DSP ENGINE] Acionando Python para estilo: ${estilo}, intensidade: ${intensidade}, preview: ${isPreview}`);

        const pythonProcess = spawn('python3', [
            pythonScriptPath, 
            inputPath, 
            outputPath, 
            estilo, 
            intensidade,
            isPreview 
        ]);

        let pythonErrorOutput = '';

        pythonProcess.stdout.on('data', (data) => {
            const output = data.toString().trim();
            console.log(`[PYTHON STDOUT]: ${output}`);
            if (output.startsWith('SUCESSO')) {
                const logs = output.split('|');
                console.log(`[DSP ENGINE] Masterização concluída com sucesso!`);
                
                res.download(outputPath, 'rqs_master.wav', () => {
                    if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                    if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                });
            } else if (output.startsWith('ERRO')) {
                console.error(`[CRITICAL] Python Reportou Erro: ${output}`);
                if (!res.headersSent) res.status(500).json({ error: output });
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            pythonErrorOutput += data.toString();
            console.error(`[PYTHON STDERR]: ${data.toString()}`);
        });

        pythonProcess.on('close', (code) => {
            if (code !== 0 && !res.headersSent) {
                console.error(`[CRITICAL] Processo Python finalizou com código de erro ${code}`);
                res.status(500).json({ error: 'Falha interna no motor de DSP Python', details: pythonErrorOutput });
            }
        });

    } catch (error) {
        console.error('[CRITICAL] Exceção crítica no roteador de DSP:', error);
        if (!res.headersSent) res.status(500).json({ error: 'Erro no roteamento interno' });
    }
});

module.exports = router;