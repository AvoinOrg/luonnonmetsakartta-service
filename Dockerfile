FROM python:3.12

SHELL ["/bin/bash", "-l", "-c"]

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update -y &&\ 
    # apt-get install autossh -y &&\
    # apt-get install chromium -y &&\
    pip install poetry &&\
    touch /root/.bash_history &&\
    echo 'PS0="$PS0"'"'"'$(history -a)'"'" >> /root/.bashrc &&\
    echo 'PROMPT_COMMAND="history -n; $PROMPT_COMMAND"' >> /root/.bashrc &&\
    printf "  PasswordAuthentication yes\n  KbdInteractiveAuthentication yes" >> /etc/ssh/ssh_config &&\
    sed -i '1,6d' /root/.bashrc &&\
    echo "source \"\$(poetry env info --path)/bin/activate\"" >> /root/.bashrc
