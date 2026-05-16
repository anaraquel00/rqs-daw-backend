const fs = require('fs');
const path = require('path');
const ffmpeg = require('fluent-ffmpeg');

// 🛡️ Mapeamento de Rotas
const inputDir = path.join(__dirname, 'blueprint-inputs');
const outputDir = path.join(__dirname, 'dist');
const vignettePath = path.join(__dirname, 'assets', 'VIGNETTE_MAIN.mp3'); // 👈 NOVO: O Cofre da Vinheta
const outputFile = path.join(outputDir, 'THE_BLUEPRINT_SESSIONS_VOL_004.mp3');

// Validação de Integridade do Barramento
if (!fs.existsSync(vignettePath)) {
    console.error('🚫 Erro: VIGNETTE_MAIN.mp3 não encontrada na pasta /assets.');
    process.exit(1);
}

// Lê e ordena as tracks geradas pelo Suno 5.5
const files = fs.readdirSync(inputDir)
    .filter(file => file.endsWith('.mp3') || file.endsWith('.wav'))
    .sort();

if (files.length === 0) {
    console.error('🚫 Erro de Compilação: Nenhum artefato de áudio encontrado em /blueprint-inputs.');
    process.exit(1);
}

console.log(`💻 Iniciando RQS_DAW Engine. Preparando a Vinheta + ${files.length} tracks...`);

let command = ffmpeg();

// 1. INJETA A VINHETA NO CANAL 0 (A Prioridade)
command.input(vignettePath);

// 2. INJETA AS MÚSICAS NOS CANAIS 1 até N
files.forEach(file => command.input(path.join(inputDir, file)));

let complexFilter = [];
let lastOutput = '1:a'; // As músicas agora começam no índice 1

// 3. COSTURA AS MÚSICAS (Crossfade de 8s)
if (files.length > 1) {
    for (let i = 2; i <= files.length; i++) {
        let nextInput = `${i}:a`;
        let currentOutput = `xfade${i}`;

        complexFilter.push({
            filter: 'acrossfade',
            options: { d: 8 }, 
            inputs: [lastOutput, nextInput],
            outputs: currentOutput
        });

        lastOutput = currentOutput;
    }
}

// 4. PROTOCOLO DE SOBREPOSIÇÃO (ID Drop)
// Atrasamos a vinheta em 3000ms (3 segundos) para a base musical respirar primeiro
complexFilter.push({
    filter: 'adelay',
    options: '3000|3000', // Atrasa o canal L e R
    inputs: '0:a',
    outputs: 'vignette_delayed'
});

// Regulamos a Master Musical para 80% do volume para dar clareza à locutora
complexFilter.push({
    filter: 'volume',
    options: '0.8',
    inputs: lastOutput,
    outputs: 'music_ducked'
});

// Somamos os dois barramentos sem cortar o tempo da música (duration=longest)
// normalize=0 evita que o FFmpeg abaixe o volume global para sempre
complexFilter.push({
    filter: 'amix',
    options: { inputs: 2, duration: 'longest', normalize: 0 },
    inputs: ['vignette_delayed', 'music_ducked'],
    outputs: 'final_master'
});

// Aplica o filtro e mapeia a saída final
command.complexFilter(complexFilter, 'final_master');

// Execução e Monitoramento de Logs
command
    .on('start', (commandLine) => {
        console.log('⚙️ Compilando pacote de frequências com Assinatura RQS...');
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