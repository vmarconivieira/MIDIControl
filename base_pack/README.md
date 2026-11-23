# Base Pack (Template Binário do P61x Console)

Este diretório contém o template base (`base_template.apk`) dividido em partes de até 45 MB para respeitar o limite de tamanho de arquivo do GitHub sem perder nenhum SoundFont (`.sf2`), sample de Pad/Drum (`.wav`) ou biblioteca nativa DSP (`libstagerig_dsp.so`, `libfluidsynth.so`, `liboboe.so`).

Durante o build (`scripts/build_apk.sh`), as partes são remontadas automaticamente, validadas via `base_template.sha256` e combinadas com o `AndroidManifest.xml`, recursos `aapt2`, `classes.dex` corrigido e `ui/index.html` mais recentes.
