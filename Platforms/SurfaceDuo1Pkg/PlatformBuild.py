# @file
# Script to Build SurfaceDuo1 Mu UEFI firmware
#
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: BSD-2-Clause-Patent
##
import os
import logging
import io
import shutil
import glob
import time
import xml.etree.ElementTree
import tempfile
import importlib

from edk2toolext.environment import shell_environment
from edk2toolext.environment.uefi_build import UefiBuilder
from edk2toolext.invocables.edk2_platform_build import BuildSettingsManager
from edk2toolext.invocables.edk2_setup import SetupSettingsManager, RequiredSubmodule
from edk2toolext.invocables.edk2_update import UpdateSettingsManager
from edk2toolext.invocables.edk2_pr_eval import PrEvalSettingsManager
from edk2toollib.utility_functions import RunCmd

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'PythonLibs'))
import sdbuild


    # ####################################################################################### #
    #                                Common Configuration                                     #
    # ####################################################################################### #
class CommonPlatform():
    ''' Common settings for this platform.  Define static data here and use
        for the different parts of stuart
    '''
    PackagesSupported = ("SurfaceDuo1Pkg",)
    ArchSupported = ("AARCH64")
    TargetsSupported = ("DEBUG", "RELEASE", "NOOPT")
    Scopes = ('SurfaceDuo1', 'edk2-build', 'cibuild')
    WorkspaceRoot = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    PackagesPath = ("Platforms", "MU_BASECORE", "Common/MU", "Common/MU_TIANO", "Common/MU_OEM_SAMPLE", "Silicon/ARM/TIANO")


    # ####################################################################################### #
    #                         Configuration for Update & Setup                                #
    # ####################################################################################### #
class SettingsManager(UpdateSettingsManager, SetupSettingsManager, PrEvalSettingsManager):

    def GetPackagesSupported(self):
        ''' return iterable of edk2 packages supported by this build.
        These should be edk2 workspace relative paths '''
        return CommonPlatform.PackagesSupported

    def GetArchitecturesSupported(self):
        ''' return iterable of edk2 architectures supported by this build '''
        return CommonPlatform.ArchSupported

    def GetTargetsSupported(self):
        ''' return iterable of edk2 target tags supported by this build '''
        return CommonPlatform.TargetsSupported

    def GetRequiredSubmodules(self):
        ''' return iterable containing RequiredSubmodule objects.
        If no RequiredSubmodules return an empty iterable
        '''
        rs = []

        # To avoid maintenance of this file for every new submodule
        # lets just parse the .gitmodules and add each if not already in list.
        # The GetRequiredSubmodules is designed to allow a build to optimize
        # the desired submodules but it isn't necessary for this repository.
        result = io.StringIO()
        ret = RunCmd("git", "config --file .gitmodules --get-regexp path",
                     workingdir=self.GetWorkspaceRoot(), outstream=result)
        # Cmd output is expected to look like:
        # submodule.CryptoPkg/Library/OpensslLib/openssl.path CryptoPkg/Library/OpensslLib/openssl
        # submodule.SoftFloat.path ArmPkg/Library/ArmSoftFloatLib/berkeley-softfloat-3
        if ret == 0:
            for line in result.getvalue().splitlines():
                _, _, path = line.partition(" ")
                if path is not None:
                    if path not in [x.path for x in rs]:
                        # add it with recursive since we don't know
                        rs.append(RequiredSubmodule(path, True))
        return rs

    def SetArchitectures(self, list_of_requested_architectures):
        ''' Confirm the requests architecture list is valid and configure SettingsManager
        to run only the requested architectures.

        Raise Exception if a list_of_requested_architectures is not supported
        '''
        unsupported = set(list_of_requested_architectures) - \
            set(self.GetArchitecturesSupported())
        if(len(unsupported) > 0):
            errorString = (
                "Unsupported Architecture Requested: " + " ".join(unsupported))
            logging.critical( errorString )
            raise Exception( errorString )
        self.ActualArchitectures = list_of_requested_architectures

    def GetWorkspaceRoot(self):
        ''' get WorkspacePath '''
        return CommonPlatform.WorkspaceRoot

    def GetActiveScopes(self):
        ''' return tuple containing scopes that should be active for this process '''
        return CommonPlatform.Scopes

    def FilterPackagesToTest(self, changedFilesList: list, potentialPackagesList: list) -> list:
        ''' Filter other cases that this package should be built
        based on changed files. This should cover things that can't
        be detected as dependencies. '''
        build_these_packages = []
        possible_packages = potentialPackagesList.copy()
        for f in changedFilesList:
            # BaseTools files that might change the build
            if "BaseTools" in f:
                if os.path.splitext(f) not in [".txt", ".md"]:
                    build_these_packages = possible_packages
                    break

            # if the azure pipeline platform template file changed
            if "platform-build-run-steps.yml" in f:
                build_these_packages = possible_packages
                break

        return build_these_packages

    def GetPlatformDscAndConfig(self) -> tuple:
        ''' If a platform desires to provide its DSC then Policy 4 will evaluate if
        any of the changes will be built in the dsc.

        The tuple should be (<workspace relative path to dsc file>, <input dictionary of dsc key value pairs>)
        '''
        return ("SurfaceDuo1Pkg/SurfaceDuo1.dsc", {})

    def GetName(self):
        return "SurfaceDuo1"

    def GetPackagesPath(self):
        ''' Return a list of paths that should be mapped as edk2 PackagesPath '''
        return CommonPlatform.PackagesPath

    # ####################################################################################### #
    #                         Actual Configuration for Platform Build                         #
    # ####################################################################################### #
class PlatformBuilder( UefiBuilder, BuildSettingsManager):
    def __init__(self):
        UefiBuilder.__init__(self)
        sdbuild.builder = self

    def AddCommandLineOptions(self, parserObj):
        ''' Add command line options to the argparser '''

        # In an effort to support common server based builds this parameter is added.  It is
        # checked for correctness but is never uses as this platform only supports a single set of
        # architectures.
        parserObj.add_argument('-a', "--arch", dest="build_arch", type=str, default="AARCH64",
            help="Optional - CSV of architecture to build. AARCH64 will use AARCH64 for PEI and "
            "AARCH64 for DXE and is the only valid option for this platform.")

    def RetrieveCommandLineOptions(self, args):
        '''  Retrieve command line options from the argparser '''
        if args.build_arch.upper() != "AARCH64":
            raise Exception("Invalid Arch Specified.  Please see comments in PlatformBuild.py::PlatformBuilder::AddCommandLineOptions")


    def GetWorkspaceRoot(self):
        ''' get WorkspacePath '''
        return CommonPlatform.WorkspaceRoot

    def GetPackagesPath(self):
        ''' Return a list of workspace relative paths that should be mapped as edk2 PackagesPath '''
        return CommonPlatform.PackagesPath

    def GetActiveScopes(self):
        ''' return tuple containing scopes that should be active for this process '''
        return CommonPlatform.Scopes

    def GetOutputDirectory(self):
        ''' Return the output directory for this platform '''
        return self.env.GetValue("OUTPUT_DIRECTORY")

    def GetOutputBinDirectory(self):
        ''' Return the output directory with binaries '''
        toolchain_tag = self.env.GetValue("TOOL_CHAIN_TAG")
        target = self.env.GetValue("TARGET")
        out_dir = self.env.GetValue("OUTPUT_DIRECTORY")
        return os.path.join(out_dir, f"{target}_{toolchain_tag}")

    def GetTargetDeviceDirectory(self):
        ''' Return the output directory with binaries '''
        target_device = self.env.GetValue("TARGET_DEVICE")
        return os.path.join("Platforms", "SurfaceDuo1Pkg", "Device", target_device)

    def GetDTBName(self):
        ''' Return the name of device's dtb '''
        target_device = self.env.GetValue("TARGET_DEVICE")
        linenum = target_device.find('-') + 1
        #print("The num is fsfsds: "+linenum);
        dtbname = target_device[(linenum):] + '.dtb'
        return dtbname

    def GetName(self):
        ''' Get the name of the repo, platform, or product being build '''
        ''' Used for naming the log file, among others '''
        return "SurfaceDuo1Pkg"

    def GetLoggingLevel(self, loggerType):
        ''' Get the logging level for a given type
        base == lowest logging level supported
        con  == Screen logging
        txt  == plain text file logging
        md   == markdown file logging
        '''
        return logging.INFO
        return super().GetLoggingLevel(loggerType)

    def SetPlatformEnv(self):
        logging.debug("PlatformBuilder SetPlatformEnv")
        self.env.SetValue("PRODUCT_NAME", "SurfaceDuo1", "Platform Hardcoded")
        self.env.SetValue("ACTIVE_PLATFORM", "SurfaceDuo1Pkg/SurfaceDuo1.dsc", "Platform Hardcoded")
        self.env.SetValue("TARGET_ARCH", "AARCH64", "Platform Hardcoded")
        self.env.SetValue("EMPTY_DRIVE", "FALSE", "Default to false")
        self.env.SetValue("RUN_TESTS", "FALSE", "Default to false")
        self.env.SetValue("QEMU_HEADLESS", "FALSE", "Default to false")
        self.env.SetValue("SHUTDOWN_AFTER_RUN", "FALSE", "Default to false")
        # needed to make FV size build report happy
        self.env.SetValue("BLD_*_BUILDID_STRING", "Unknown", "Default")
        # Default turn on build reporting.
        self.env.SetValue("BUILDREPORTING", "TRUE", "Enabling build report")
        self.env.SetValue("BUILDREPORT_TYPES", "PCD DEPEX FLASH BUILD_FLAGS LIBRARY FIXED_ADDRESS HASH", "Setting build report types")
        # Include the MFCI test cert by default, override on the commandline with "BLD_*_SHIP_MODE=TRUE" if you want the retail MFCI cert
        self.env.SetValue("BLD_*_SHIP_MODE", "FALSE", "Default")
        self.env.SetValue("BLD_*_TARGET_DEVICE", self.env.GetValue("TARGET_DEVICE"), "Default")
        self.env.SetValue("BLD_*_TARGET_RAM_SIZE", self.env.GetValue("TARGET_RAM_SIZE"), "Default")
        self.env.SetValue("BLD_*_MODEL", self.env.GetValue("MODEL"), "Default")
        self.env.SetValue("BLD_*_RETAILMODEL", self.env.GetValue("RETAILMODEL"), "Default")
        self.env.SetValue("BLD_*_RETAILSKU", self.env.GetValue("RETAILSKU"), "Default")
        self.env.SetValue("BLD_*_BOARDMODEL", self.env.GetValue("BOARDMODEL"), "Default")
        self.env.SetValue("BLD_*_FDT", self.GetDTBName(), "Default")
        return 0

    def PlatformPreBuild(self):
        self.RunTargetDeviceScript("PreBuild.py")
        return 0

    def PlatformPostBuild(self):
        self.RunTargetDeviceScript("..//..//PostBuild.py")
        return 0

    def RunTargetDeviceScript(self, script_name):
        script_file = os.path.join(self.GetTargetDeviceDirectory(), script_name)
        if os.path.exists(script_file):
            logging.info("Running %s", script_name)
            loader = importlib.machinery.SourceFileLoader(script_name, script_file)
            spec = importlib.util.spec_from_loader(loader.name, loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)


    def FlashRomImage(self):
        return 0



if __name__ == "__main__":
    import argparse
    import sys
    from edk2toolext.invocables.edk2_update import Edk2Update
    from edk2toolext.invocables.edk2_setup import Edk2PlatformSetup
    from edk2toolext.invocables.edk2_platform_build import Edk2PlatformBuild
    print("Invoking Stuart")
    print("     ) _     _")
    print("    ( (^)-~-(^)")
    print("__,-.\_( 0 0 )__,-.___")
    print("  'W'   \   /   'W'")
    print("         >o<")
    SCRIPT_PATH = os.path.relpath(__file__)
    parser = argparse.ArgumentParser(add_help=False)
    parse_group = parser.add_mutually_exclusive_group()
    parse_group.add_argument("--update", "--UPDATE",
                             action='store_true', help="Invokes stuart_update")
    parse_group.add_argument("--setup", "--SETUP",
                             action='store_true', help="Invokes stuart_setup")
    args, remaining = parser.parse_known_args()
    new_args = ["stuart", "-c", SCRIPT_PATH]
    new_args = new_args + remaining
    sys.argv = new_args
    if args.setup:
        print("Running stuart_setup -c " + SCRIPT_PATH)
        Edk2PlatformSetup().Invoke()
    elif args.update:
        print("Running stuart_update -c " + SCRIPT_PATH)
        Edk2Update().Invoke()
    else:
        print("Running stuart_build -c " + SCRIPT_PATH)
        Edk2PlatformBuild().Invoke()
