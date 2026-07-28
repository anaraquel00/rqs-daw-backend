const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// ====================================================================
// 1. Configuração do Arsenal de Entrada (Multer via Disco Efêmero /tmp) [1]
// ====================================================================
// 🟢 CORREÇÃO: Evita estouro de RAM ao fazer streaming do arquivo diretamente para o SSD temporário do Lambda [1.1.2]
const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, '/tmp/'),
    filename: (req, file, cb) => cb(null, `input_${Date.now()}_${file.originalname}`)
});
const upload = multer({ storage });

// 2. A Rota de Processamento (/api/v1/mastering/process)
router.post('/process', upload.any(), (req, res) => {
    try {
        console.log('[DSP ENGINE] Requisição HTTP recebida na AWS Lambda.');
        
        const uploadedFile = req.files && req.files.length > 0 ? req.files[0] : null;

        if (!uploadedFile) {
            console.error('[CRITICAL] Nenhum arquivo binário encontrado no payload.');
            return res.status(400).json({ error: 'Nenhum arquivo de áudio enviado.' });
        }

        // O arquivo já foi gravado de forma segura no /tmp diretamente pelo Multer! [1.1.2]
        const inputPath = uploadedFile.path;

        const estilo = req.body.estilo || 'clear_sky';
        const intensidade = req.body.intensidade || 'media';
        const outputPath = path.join('/tmp', `output_${Date.now()}.wav`);
        const pythonScriptPath = path.join(__dirname, 'core_dsp.py');
        const isPreview = req.body.preview === 'true' ? 'true' : 'false';

        console.log(`[DSP ENGINE] Acionando Python para estilo: ${estilo}, intensidade: ${intensidade}, preview: ${isPreview}`);

        // ====================================================================
        // 3. Invoca o Motor Python com Roteamento Absoluto do Contêiner
        // ====================================================================
        // 🟢 CORREÇÃO: Aponta exatamente para o venv definido na Linha 17 da sua Dockerfile!
        const venvPython = '/opt/venv/bin/python3';
        const pythonProcess = spawn(venvPython, [
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
                console.log(`[DSP ENGINE] Masterização concluída com sucesso!`);
                
                res.download(outputPath, 'rqs_master.wav', () => {
                    // Limpeza pós-transmissão bem sucedida [1]
                    if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                    if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                });
            } else if (output.startsWith('ERRO')) {
                console.error(`[CRITICAL] Python Reportou Erro: ${output}`);
                if (!res.headersSent) res.status(500).json({ error: output });
                // Limpeza em caso de erro interno relatado pelo script
                if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            pythonErrorOutput += data.toString();
            console.error(`[PYTHON STDERR]: ${data.toString()}`);
        });

        pythonProcess.on('close', (code) => {
            // 🟢 CORREÇÃO: Blinda contra exaustão de disco no /tmp limpando arquivos se o Python sofrer um crash [1]
            if (code !== 0) {
                console.error(`[CRITICAL] Processo Python finalizou com código de erro ${code}`);
                if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                
                if (!res.headersSent) {
                    res.status(500).json({ error: 'Falha interna no motor de DSP Python', details: pythonErrorOutput });
                }
            }
        });

    } catch (error) {
        console.error('[CRITICAL] Exceção crítica no roteador de DSP:', error);
        if (!res.headersSent) res.status(500).json({ error: 'Erro no roteamento interno' });
    }
});

module.exports = router;