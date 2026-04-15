---
layout: post
title: "How to resize a UTM VM"
categories:
tags:
  - linux
  - how-to
---

Although I ostensibly call myself a compilers person, I keep finding myself in OS-land {% sidenote 'arca' "ie. check out [arca](https://github.com/fix-project/arca), an operating system designed around using continuations as the primary isolation primitive to give serverless providers more scheduling flexibility."%}. In my current foray into OS-land, I’m trying to build a custom Linux kernel with a different page allocator. 

I pretty much just followed [the setup guide for Virginia Tech’s Advanced Linux Kernel Programming Course](https://people.cs.vt.edu/huaicheng/lkp-sp26/resources/environment-setup/) to get a Linux VM up and running so I can hack at the kernel, but I screwed up and didn't allocate enough space for it. Oops!

Here's a quick guide for other silly people like me.

---

*Oh no! I’ve run out of disk space!*

First, shutdown your VM{% sidenote 'poweroff' "I prefer `poweroff` over `shutdown` to avoid the historical 60s delay."%}. 

From UTM, right click your VM to edit it, and then resize the VM from the "Disk VirtIO" tab.

This might not solve your problems though, since I've noticed this resizes the VM physically without updating the logical partitions, and `lsblk` returns something like
```
NAME                      MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
sr0                        11:0    1  2.8G  0 rom
vda                       253:0    0   64G  0 disk
├─vda1                    253:1    0    1G  0 part /boot/efi
├─vda2                    253:2    0    2G  0 part /boot
└─vda3                    253:3    0 28.9G  0 part
  └─ubuntu--vg-ubuntu--lv 252:0    0 28.9G  0 lvm  /
```

By default, the filesystem should be backed by [LVM/LVM2](https://en.wikipedia.org/wiki/Logical_Volume_Manager_(Linux)), which allows you, the sysadmin, to resize logical partitions as needed. Run the following commands to also update the size of your logical partition:

```
# 1. Grow the partition to use remaining free space
sudo growpart /dev/vda 3

# 2. Resize the LVM physical volume to see the new space
sudo pvresize /dev/vda3

# 3. Extend the logical volume to use 100% of free space
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv

# 4. Resize the filesystem live (no unmount needed for ext4)
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv
```

*PS: Like literally everything on this site, this is really just for future Katherine so I don't forget my own setup steps.*

*PPS: I didn't even end up using this setup, my actual workflow is decently well-documented in [this README.md](https://github.com/katherinemohr/ltram-policy-bench/blob/main/README.md).*
