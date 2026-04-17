# Hypha default firejail profile.
# Review every line before enabling M5 in production.

# Filesystem: no access outside cwd whitelist (applied by the runner).
private-dev
private-tmp
private-etc alternatives,resolv.conf,ca-certificates,ssl

# Capabilities / syscalls: drop everything not strictly needed.
caps.drop all
seccomp
noroot
nonewprivs
nogroups
nosound
no3d
notv
nodvd
nou2f

# No network at all (reinforced by --net=none on the command line).
netfilter

# Disable common escape surfaces.
shell none
disable-mnt
