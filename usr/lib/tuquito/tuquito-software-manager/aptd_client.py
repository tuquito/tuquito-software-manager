#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
 Gestor de programas 1.1
 Copyright (C) 2010
 Author: Mario Colque <mario@tuquito.org.ar>
 Tuquito Team! - www.tuquito.org.ar

 This program is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; version 3 of the License.
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 GNU General Public License for more details.
 You should have received a copy of the GNU General Public License
 along with this program; if not, write to the Free Software
 Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA.
"""

import aptdaemon, sys, gettext
from aptdaemon.client import AptClient

# i18n
gettext.install("tuquito-software-manager", "/usr/share/tuquito/locale")

if len(sys.argv) == 3:
	operation = sys.argv[1]
	package = sys.argv[2]
	aptd_client = AptClient()
	if operation == "install":
		transaction = aptd_client.install_packages([package])
		transaction.set_meta_data(mintinstall_label=_("Installing %s") % package)
	elif operation == "remove":
		transaction = aptd_client.remove_packages([package])
		transaction.set_meta_data(mintinstall_label=_("Removing %s") % package)
	else:
		print "Invalid operation: %s" % operation
		sys.exit(1)
	transaction.set_meta_data(mintinstall_pkgname=package)
	transaction.run()
