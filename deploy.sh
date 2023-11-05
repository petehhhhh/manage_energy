git add .
git commit -m "$1"
git push origin main
ssh root@10.0.4.235 'cp -r /config/custom_components/manage_energy/* /config/manage_energy_old'
scp -r /workspaces/core/config/custom_components/manage_energy/* root@10.0.4.235:/config/custom_components/manage_energy/
ssh root@10.0.4.235 'ha core restart'&
