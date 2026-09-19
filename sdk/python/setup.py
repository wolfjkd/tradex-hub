"""tradex_client SDK 安装配置（工单 22）。"""

from setuptools import setup, find_packages

setup(
    name="tradex-client",
    version="0.1.0",
    description="Auto-generated Python client for tradex-hub REST API",
    long_description="见 sdk/README.md",
    long_description_content_type="text/markdown",
    license="Apache-2.0",
    requires_python=">=3.9",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
    ],
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Topic :: Office/Business :: Financial",
    ],
)
