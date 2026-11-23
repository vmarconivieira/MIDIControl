# P61x Console — Android Stage Rig Workstation

Repositório oficial de versionamento, build reproduzível e atualizações via GitHub do **P61x Console** (`com.p61x.keyboard`) para Android (otimizado para Samsung Galaxy M55 / Android 14–16).

## Estrutura do Projeto

- [`version.json`](version.json) — Versão vigente (`versionCode`, `versionName`, `tag`, `apkUrl`, `notes`), lida pelo app e pelo GitHub Actions.
- [`ui/index.html`](ui/index.html) — Interface WebView mobile (Mixer, Pads, Drums, Knobs ampliados, Modal de Setlist/Timbres, Config MIDI, Atualizador GitHub e faders acelerados por GPU).
- [`android/AndroidManifest.xml`](android/AndroidManifest.xml) & [`android/res/`](android/res/) — Manifesto Android (`INTERNET`, `REQUEST_INSTALL_PACKAGES`, `UpdateInstallReceiver`) e recursos compilados via `aapt2`.
- [`android/src/com/p61x/keyboard/`](android/src/com/p61x/keyboard/) — Módulos Java nativos:
  - `P61xPatch.java` — Correção do modo imersivo no Android 14–16, ciclo de vida seguro e sincronização pós-carregamento da WebView.
  - `P61xUpdater.java` & `UpdateInstallReceiver.java` — Verificação de versão no GitHub Releases / `version.json`, download em streaming direto para `PackageInstaller.Session` e instalação no aparelho.
  - `UsbMidiEnhanced.java` — Detecção USB MIDI reforçada (API 27–35+ `MidiManager` + `TRANSPORT_MIDI_BYTE_STREAM`, `BroadcastReceiver` de USB attach/detach, retries escalonados, limpeza de portas e filtro por porta/modo automático).
- [`tools/`](tools/) — `DexPatcher.java`, `DexVerifier.java` e `verify_apk.py` (validação completa de DEX, `@JavascriptInterface`, manifesto, alinhamento 16 KB e assinatura v1+v2+v3).
- [`scripts/build_apk.sh`](scripts/build_apk.sh) — Build completo e reproduzível do APK.
- [`base_pack/`](base_pack/) — Template base dividido em blocos de 45 MB (SoundFonts `.sf2`, samples WAV, DSP nativo `libstagerig_dsp.so` / `libfluidsynth.so` / `liboboe.so` e classes base) com verificação SHA-256.
- [`.github/workflows/release-apk.yml`](.github/workflows/release-apk.yml) — Pipeline automático que compila, verifica e publica o APK em **GitHub Releases**.

## Como Publicar uma Nova Versão (Atualização Automática no App)

1. Faça suas alterações em `ui/index.html` ou `android/src/`.
2. Atualize [`version.json`](version.json) incrementando `versionCode` (ex: `3`), `versionName` (ex: `"1.2.0"`), `tag` (`"v1.2.0"`), `apkFileName`, `apkUrl`, `releaseUrl` e `notes`.
3. Faça commit, crie a tag e envie para o GitHub:
   ```bash
   git add -A
   git commit -m "Release v1.2.0"
   git tag v1.2.0
   git push origin main --tags
   ```
4. O workflow **Build & Release P61x Console APK** no GitHub Actions gera automaticamente o APK assinado e publica na aba **Releases**.
5. Ao abrir o P61x Console no celular, o app detecta que a versão vigente no GitHub difere da versão instalada, exibe o aviso em **Menu → Atualizações (GitHub)** e permite baixar e atualizar diretamente!

## Configurando a Chave de Assinatura (Secrets no GitHub)

Para que os APKs compilados pelo GitHub Actions atualizem **por cima** da versão instalada no celular (sem precisar desinstalar e sem perder presets), configure estes 4 Secrets em **Settings → Secrets and variables → Actions**:

| Secret | Descrição |
| --- | --- |
| `ANDROID_KEYSTORE_B64` | Arquivo `.jks` codificado em Base64 (`base64 -w0 p61x_release.jks`) |
| `ANDROID_KEYSTORE_PASS` | Senha da keystore |
| `ANDROID_KEY_ALIAS` | Alias da chave (`p61x_release`) |
| `ANDROID_KEY_PASS` | Senha da chave |

## Build Local

```bash
KEYSTORE_PATH=/caminho/p61x_release.jks \
KEYSTORE_PASS=sua_senha \
KEY_ALIAS=p61x_release \
KEY_PASS=sua_senha \
./scripts/build_apk.sh
```
