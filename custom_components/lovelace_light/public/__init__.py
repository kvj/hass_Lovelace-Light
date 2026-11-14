def locate_dir():
    return __path__[0]

LL_HTML = """
<!doctype html>
<html>
    <head>
      <meta charset="utf-8" />
      <link rel="stylesheet" href="/lovelace_light/index.css?ts={ts}" />
      <link rel="stylesheet" href="/lovelace_light/{slug}.extra.css?ts={ts}" />
      <script>
        const lovelaceLightDashboard = {{
            "slug": "{slug}",
            "id": "{id}",
            "page": "{page}",
        }};
        const lovelaceLightConfig = {{
          {config}
        }};
      </script>
      <script type="module" src="/lovelace_light/index.js?ts={ts}"></script>
    </head>
    <body class="body">
    <div id="root" class="dashboard"></div>
    <div id="connection" class="connection_indicator"></div>
    </body>
</html>
"""

LL_CSS = """
{extra_css}
"""
