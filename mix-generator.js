const fs = require('fs');
const path = require('path');
const ffmpeg = require('fluent-ffmpeg');end

// 🛡️ Mapeamento de Rotas
const inputDir = path.join(__dirname, 'blueprint-inputs');
const outputDir = path.join(__dirname, 'dist');
const outputFile = path.join(outputDir, 'THE_BLUEPRINT_SESSIONS_VOL_002.mp3');

// Lê e ordena as tracks geradas pelo Suno 5.5
const files = fs.readdirSync(inputDir)
    .filter(file => file.endsWith('.mp3') || file.endsWith('.wav'))
    .sort();

if (files.length === 0) {
    console.error('🚫 Erro de Compilação: Nenhum artefato de áudio encontrado em /blueprint-inputs.');
    process.exit(1);
}

console.log(`💻 Iniciando RQS_DAW Engine. Preparando ${files.length} tracks para o Volume 002...`);

let command = ffmpeg();

// Injeta os arquivos no motor
files.forEach(file => command.input(path.join(inputDir, file)));

// Lógica Arquitetural de Crossfade Dinâmico (8 segundos de transição)
if (files.length > 1) {
    let complexFilter = [];
    let lastOutput = '0:a';

    for (let i = 1; i < files.length; i++) {
        let nextInput = `${i}:a`;
        let currentOutput = `a${i}`;

        complexFilter.push({
            filter: 'acrossfade',
            options: { d: 8 }, // d = duration (8 segundos de transição hipnótica)
            inputs: [lastOutput, nextInput],
            outputs: currentOutput
        });

        lastOutput = currentOutput;
    }

    command.complexFilter(complexFilter, lastOutput);
}

// Execução e Monitoramento de Logs
command
    .on('start', (commandLine) => {
        console.log('⚙️ Compilando pacote de frequências...');
    })
    .on('progress', (progress) => {
        if (progress.targetSize) {
            process.stdout.write(`\r[Processamento]: ${progress.targetSize} KB renderizados...`);
        }
    })
    .on('end', () => {
        console.log('\n💎 Deploy concluído com sucesso! A Master foi salva no diretório /dist.');
    })
    .on('error', (err) => {
        console.error('\n🛡️ Falha Crítica no Pipeline:', err.message);
    })
    .save(outputFile);
