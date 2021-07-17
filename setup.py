from setuptools import setup

setup(
    name="asyncio-pomodoro",
    version="1.0",
    description="asyncio+pyside-based pomodoro timer",
    url="https://github.com/fmqa/asyncio-pomodoro",
    author="fmqa",
    author_email="7354509+fmqa@users.noreply.github.com",
    license="MIT",
    packages=["aiopomodoro"],
    python_requires=">=3.8",
    install_requires=[
        "PySide2>=5.15.2, <6",
        "python-dotenv>=0.18.0",
        "pyxdg>=0.27",
        "qasync>=0.17.0",
        "PyGObject>=3.36"
    ],
    entry_points={
        "gui_scripts": "asyncio-pomodoro=aiopomodoro:main"
    }
)
