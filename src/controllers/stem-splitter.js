const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// 1. Configuração do Arsenal de Entrada (Multer)
const uploadDir = path.join(__dirname, '../../../uploads/stems');
if (!fs.existsSync(uploadDir)) {
    fs.mkdirSync(uploadDir, { recursive: true });
}

const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, uploadDir),
    filename: (req, file, cb) => cb(null, `${Date.now()}-${file.originalname}`)
});
const upload = multer({ storage });

// 2. A Rota de Processamento (/api/v1/stems/split)
router.post('/split', upload.single('audio'), (req, res) => {
    if (!req.file) {
        return res.status(400).json({ error: 'Nenhum áudio recebido pela matriz.' });
    }

    const inputPath = req.file.path;
    const outputDir = uploadDir;
    // Aponta exatamente para o arquivo Python que criamos
    const scriptPath = path.join(__dirname, 'core_demucs.py');

    console.log(`[STEM SPLITTER] Iniciando extração molecular para: ${inputPath}`);

    // 3. Invoca o Motor Python em Segundo Plano
    const pyProcess = spawn('python3', [scriptPath, inputPath, outputDir]);
    // 3. Invoca o Motor Python com Roteamento Absoluto (Bypass do Servidor)
    const venvPython = path.join(__dirname, '../../../.venv/bin/python3');
    const pyProcess = spawn(venvPython, [scriptPath, inputPath, outputDir]);

    let zipPath = '';
    let errorLog = '';

    // Escuta a telemetria que o Python cospe no terminal
    pyProcess.stdout.on('data', (data) => {
        const output = data.toString();
        console.log(`[DEMUCS INFO]: ${output.trim()}`);
        if (output.includes('SUCCESS:')) {
            zipPath = output.split('SUCCESS:')[1].trim();
        }
    });

    pyProcess.stderr.on('data', (data) => {
        errorLog += data.toString();
        console.error(`[DEMUCS ERRO]: ${data.toString()}`);
    });

    // 4. Fechamento do Processo e Envio do Payload
    pyProcess.on('close', (code) => {
        if (code !== 0 || !zipPath) {
            // Em caso de falha, limpamos o áudio enviado para não acumular lixo
            if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
            return res.status(500).json({ error: 'Falha crítica na matriz do Demucs.', log: errorLog });
        }

        console.log('[STEM SPLITTER] Pacote blindado pronto. Iniciando transmissão...');

        // O Express empacota o arquivo e força o download no navegador
        res.download(zipPath, 'rqs_6_stems.zip', (err) => {
            // 5. Otimização Final: Rotina de limpeza pós-transmissão
            if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
            if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
            
            if (err) {
                console.error('[STEM SPLITTER] Erro ao transmitir o ZIP:', err);
            } else {
                console.log('[STEM SPLITTER] 6 Stems entregues com sucesso e área limpa!');
            }
        });
    });
});

module.exports = router;