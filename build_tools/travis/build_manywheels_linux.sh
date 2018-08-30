#!/bin/bash

# Modify permissions on file
set -e -x

# Compile wheels
PYTHON="/opt/python/${PYTHON_VERSION}/bin/python"
PIP="/opt/python/${PYTHON_VERSION}/bin/pip"
${PIP} install --upgrade pip wheel
${PIP} install --upgrade setuptools
${PIP} install --upgrade cython==0.23.5

# One of our envs is not building correctly anymore. Need Numpy up front since
# statsmodels 0.9.0 now requires numpy to install from pip
${PIP} install --upgrade numpy

# NOW we can install requirements
${PIP} install -r /io/requirements.txt
make -C /io/ PYTHON="${PYTHON}"
${PIP} wheel /io/ -w /io/dist/

# Bundle external shared libraries into the wheels.
for whl in /io/dist/*.whl; do
    if [[ "$whl" =~ "$PYMODULE" ]]; then
        auditwheel repair $whl -w /io/dist/ #repair pyramid_arima wheel and output to /io/dist
    fi

    rm $whl # remove wheel
done
