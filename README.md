# Agente Web de Noticias IA y Energia

Proyecto local para revisar cada manana un resumen de noticias y conversaciones relevantes sobre:

- Inteligencia artificial
- Mercado energetico

El agente consulta fuentes abiertas (RSS, APIs publicas y foros como Reddit/Hacker News cuando estan disponibles), deduplica resultados, prioriza senales y usa un modelo local para resumirlas. Despues genera una pagina web estatica.

## Publicacion segura para verlo fuera de casa

La opcion recomendada para este proyecto es publicar solo la carpeta `public/` en GitHub Pages.

- No hace falta dejar tu ordenador encendido para consultar la web.
- No necesitas abrir puertos ni exponer servicios de tu red domestica.
- Tu PC solo se usa para generar el contenido y subir los cambios.

### Separacion de contenido

- `data/`: datos de trabajo y cache local.
- `public/`: web estatica lista para publicar.

El script `scripts/update_digest.py` genera `data/digest.json` para uso local y tambien copia `digest.js` dentro de `public/`, de forma que GitHub Pages solo necesite publicar esa carpeta.

### Despliegue con GitHub Pages

1. Crea un repositorio en GitHub y sube este proyecto.
2. Usa la rama `main`.
3. En GitHub abre `Settings > Pages`.
4. En `Build and deployment`, selecciona `GitHub Actions`.
5. El workflow `.github/workflows/deploy-pages.yml` publicara automaticamente `public/` en cada `push` a `main`.

### Flujo diario

1. Ejecuta `python scripts/update_digest.py`.
2. Revisa la web en local si quieres.
3. Haz commit y push.
4. GitHub Pages republica la web.

### Checklist de privacidad

Antes de publicar, confirma estas reglas:

- No guardar claves API, tokens o passwords en `config/`, `data/` o `public/`.
- No incluir rutas locales, nombres de usuario o logs de tu equipo en el HTML generado.
- No mezclar notas privadas tuyas con los datos publicos agregados.

## Modelos locales

La configuracion por defecto usa Ollama en local con dos modelos:

- Resumen principal: `llama3.1:8b`
- Traduccion de tarjetas: `qwen2.5:3b`
- URL: `http://localhost:11434`

Instala Ollama y descarga el modelo:

```powershell
ollama pull llama3.1:8b
ollama pull qwen2.5:3b
```

Comprueba que Ollama esta arrancado:

```powershell
ollama serve
```

Puedes cambiar los modelos en `config/sources.json`, dentro de `settings.local_models`. Tambien puedes sobrescribirlos temporalmente con:

```powershell
$env:AGENTE_SUMMARY_MODEL="llama3.1:8b"
$env:AGENTE_TRANSLATION_MODEL="qwen2.5:3b"
python scripts/update_digest.py
```

Si Ollama no esta disponible, el agente deja un aviso en la pagina y usa un resumen basico para que la web no se quede rota.

## Uso rapido

1. Actualiza el informe:

```powershell
python scripts/update_digest.py
```

2. Abre la web:

```powershell
python -m http.server 8000
```

3. Entra en:

```text
http://localhost:8000/public/
```

Tambien puedes usar los accesos de Windows:

- `install_model.bat`: descarga el modelo local por defecto en Ollama.
- `run_update.bat`: actualiza el informe.
- `start_web.bat`: arranca la web en `http://localhost:8000/public/`.

## Fuentes

Las fuentes se editan en `config/sources.json`. Hay fuentes tipo:

- `rss`: RSS o Atom.
- `reddit`: subreddits ordenados por `top` del dia.
- `hn_algolia`: busquedas recientes en Hacker News por relevancia social.
- `arxiv`: articulos recientes de arXiv.

Si una fuente falla, el agente sigue con las demas y deja la incidencia en el informe.

## Automatizar por la manana

En Windows puedes crear una tarea programada que ejecute:

```powershell
python E:\DEV\Agente_Web\scripts\update_digest.py
```

Como carpeta de inicio usa:

```text
E:\DEV\Agente_Web
```
