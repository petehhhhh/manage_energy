cd /workspaces/core/config/custom_components/manage_energy
git add .
git commit -m "$1"
git push origin main
ssh root@10.0.4.235 'cp -r /root/homeassistant/custom_components/manage_energy/* /root/homeassistant/config/manage_energy_old'
if [ $? -ne 0 ]; then
    echo "Backup failed. Exiting."
    exit 1
fi

scp -r /workspaces/core/config/custom_components/manage_energy/* root@10.0.4.235:/root/homeassistant/custom_components/manage_energy/
if [ $? -ne 0 ]; then
    echo "Copy failed. Exiting."
    exit 1
fi

ssh root@10.0.4.235 'ha core restart'&


