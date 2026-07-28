const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// 🟢 MÓDULO S3: Importação dos SDKs oficiais da AWS para bypassar o limite de 6MB do gateway [1.2.6]
const { S3Client, PutObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

// Inicializa o cliente do S3 mapeado para o seu data center na AWS
const s3Client = new S3Client({ region: "us-east-1" });

// Configuração do Multer em disco efêmero para arquivos pequenos de teste (Previews) [1.1.2]
const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, '/tmp/'),
    filename: (req, file, cb) => cb(null, `input_${Date.now()}_${file.originalname}`)
});
const upload = multer({ storage });

// ============================================================================
// ROTA 1 (NOVA): GET /api/v1/mastering/presigned-url
// Permite que o Angular envie faixas WAV gigantes de 100MB direto para o S3 [1.2.6]
// ============================================================================
router.get('/presigned-url', async (req, res) => {
    try {
        const fileName = req.query.filename;
        if (!fileName) {
            return res.status(400).json({ error: "O parâmetro 'filename' é obrigatório." });
        }

        const s3Key = `uploads/${Date.now()}_${fileName}`;

        // Cria a ordem de upload seguro para o bucket S3
        const command = new PutObjectCommand({
            Bucket: "seu-bucket-de-audio-rqs", // ⚠️ Substitua pelo nome do seu Bucket real criado no console S3
            Key: s3Key,
            ContentType: "audio/wav"
        });

        // Gera a URL pré-assinada válida por 15 minutos (900 segundos) [1]
        const uploadUrl = await getSignedUrl(s3Client, command, { expiresIn: 900 });

        // Retorna a URL de upload direto e a chave do arquivo para o Angular salvar
        res.status(200).json({ uploadUrl, s3Key });
    } catch (error) {
        console.error("Erro ao gerar presigned URL no S3:", error);
        res.status(500).json({ error: "Falha na nuvem S3 ao gerar link de upload." });
    }
});

// ============================================================================
// ROTA 2: POST /api/v1/mastering/process
// O seu reator de processamento masterizador principal
// ============================================================================
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

        // Invoca o Python com o interpretador absoluto do venv do contêiner Docker
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
                if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            pythonErrorOutput += data.toString();
            console.error(`[PYTHON STDERR]: ${data.toString()}`);
        });

        pythonProcess.on('close', (code) => {
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