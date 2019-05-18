import os

if os.environ['SITE'] == 'docs':
    os.system("yarn install:prod && yarn pip:install:docs")
    os.system(
        "export PATH=`pwd`/bin:$PATH && yarn docs:prebuild && sphinx-build -W docs docs/_build/html")
    os.system('mkdir site')
    os.system("cp -r docs/_build/html site")
