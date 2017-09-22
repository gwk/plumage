#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import os
import os.path
import plistlib
import re
from argparse import ArgumentParser
from pithy.ansi import *
from pithy.io import *
from pithy.fs import copy_file, path_exists, make_dirs
from pithy.string_utils import find_and_clip_suffix
from pithy.task import *


def main():
  arg_parser = ArgumentParser(description='Build Mac Swift apps using the Swift Package Manager (without Xcode).')
  arg_parser.add_argument('-build-path', default='_build')
  arg_parser.add_argument('-name', required=True)
  arg_parser.add_argument('-identifier', required=True)
  arg_parser.add_argument('-copyright', required=True)
  arg_parser.add_argument('-deployment-target', required=True)
  arg_parser.add_argument('-sources', nargs='*', required=True)
  arg_parser.add_argument('-frameworks', nargs='*', required=True)
  args = arg_parser.parse_args()

  # TODO: all options should be written in json/config file.

  try: build(args)
  except TaskUnexpectedExit as e: exit(e.act)


def build(args):
  build_path = args.build_path
  deployment_target = args.deployment_target
  name = args.name
  sources = args.sources

  if not re.fullmatch(r'\d+\.\d+', deployment_target):
    exit(f"error: deployment target should be macOS 'MAJOR.MINOR' number; received {deployment_target!r}")

  for source in sources:
    if not path_exists(source):
      exit(f'error: source does not exist: {source!r}')

  c, dev_dir = runCO('xcode-select --print-path')
  if c: exit("error: 'xcode-select --print-path' failed.")
  dev_dir = dev_dir.rstrip('\n')

  sdk_dir = f'{dev_dir}/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk' # The versioned SDK just links to the unversioned one.
  swift_libs_dir = f'{dev_dir}/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift/macosx'
  mode_path = f'{build_path}/debug' # TODO: support other configurations.

  target_triple = 'x86_64-apple-macosx' + deployment_target

  # Build program.
  build_cmd = ['swift-plumage', '-build-path', build_path, '-target-triple', target_triple, '-product', name]
  run(build_cmd)

  # Bundle paths.
  bundle_path = f'{mode_path}/{name}.app'
  contents_path = bundle_path + '/Contents'
  frameworks_path = contents_path + '/Frameworks'
  macos_path = contents_path + '/MacOS'
  resources_path = contents_path + '/Resources'

  # Make directories.
  for path in (bundle_path, contents_path, frameworks_path, macos_path, resources_path):
    make_dirs(path)

  # Copy executable.
  exe_src = f'{build_path}/debug/{name}'
  exe_path = f'{macos_path}/{name}'
  copy_file(exe_src, exe_path)

  # Compile image assets.
  img_deps_path = f'{mode_path}/image-deps.txt'
  img_info_path = f'{mode_path}/icon.plist'
  actool_cmd = [ 'xcrun', 'actool',
    '--output-format', 'human-readable-text',
    #'--notices',
    '--warnings',
    '--export-dependency-info', img_deps_path,
    '--output-partial-info-plist', img_info_path,
    '--app-icon', 'AppIcon',
    '--enable-on-demand-resources', 'NO',
    '--target-device', 'mac',
    '--minimum-deployment-target', deployment_target,
    '--platform', 'macosx',
    '--product-type', 'com.apple.product-type.application',
    '--compile', resources_path,
    'images.xcassets']

  _ = runO(actool_cmd) # output is not helpful.
  img_deps = open(img_deps_path).read()
  img_info = plistlib.load(open(img_info_path, 'rb'))
  #errL('img_deps:\n', img_deps, '\n')
  #errP(img_info, label='img_info')

  # Generate Info.plist.
  plist_path = f'{contents_path}/Info.plist'
  with open(plist_path, 'wb') as f:
    gen_plist(f,
      EXECUTABLE_NAME=name,
      PRODUCT_BUNDLE_IDENTIFIER=args.identifier,
      PRODUCT_NAME=name,
      MACOSX_DEPLOYMENT_TARGET=deployment_target,
      copyright=args.copyright,
      principle_class='NSApplication',
      **img_info)

  # Find swift source paths.
  swift_imports_path = f'{mode_path}/{name}-swift-imports.txt'
  find_cmd = ['find', '-s'] + sources + ['-name', '*.swift']
  swift_source_paths = list(filter(None, runO(find_cmd).split('\n'))) # TODO: use run_gen.

  # Detect swift imports.
  egrep_cmd = ['egrep', '--no-filename', '--only-matching', r'\s*import .*'] + swift_source_paths
  swift_import_lines = list(filter(None, runO(egrep_cmd).split('\n'))) # TODO: use run_gen.
  swift_imports = sorted(set(trim_import_statement(line) for line in swift_import_lines))

  # Copy swift libs.
  swift_libs = set(required_libs)
  swift_libs.update(debug_libs)
  swift_libs.update(swift_imports)

  for import_name in swift_imports:
    if import_name in system_frameworks:
      lib_name = f'libswift{import_name}.dylib'
      src_path = f'{swift_libs_dir}/{lib_name}'
      dst_path = f'{frameworks_path}/{lib_name}'
      if not path_exists(dst_path):
        copy_file(src_path, dst_path)
    else:
      pass
      #errSL('note: ignoring unknown import:', import_name)

  # Copy frameworks.

  # Touch the bundle.
  run(['touch', '-c', bundle_path])

  # TODO: register with launch services?


def gen_plist(dst_file, EXECUTABLE_NAME, PRODUCT_BUNDLE_IDENTIFIER, PRODUCT_NAME, MACOSX_DEPLOYMENT_TARGET, copyright, principle_class, **items):
  d = {
    'BuildMachineOSBuild': '17A362a', # TODO.
    'CFBundleDevelopmentRegion': 'en',
    'CFBundleExecutable': EXECUTABLE_NAME,
    'CFBundleIdentifier': PRODUCT_BUNDLE_IDENTIFIER,
    'CFBundleInfoDictionaryVersion': '6.0',
    'CFBundleName': PRODUCT_NAME,
    'CFBundlePackageType': 'APPL',
    'CFBundleShortVersionString': '1.0', # TODO.
    'CFBundleSignature': '????',
    'CFBundleSupportedPlatforms': ['MacOSX'],
    'CFBundleVersion': '1', # TODO.
    'DTCompiler': 'com.apple.compilers.llvm.clang.1_0', # TODO.
    'DTPlatformBuild': '9A235', # TODO.
    'DTPlatformVersion': 'GM', # TODO.
    'DTSDKBuild': '17A360', # TODO.
    'DTSDKName': 'macosx10.13', # TODO.
    'DTXcode': '0900', # TODO.
    'DTXcodeBuild': '9A235', # TODO.
    'LSMinimumSystemVersion': MACOSX_DEPLOYMENT_TARGET,
    'NSHumanReadableCopyright': copyright,
    'NSPrincipalClass': principle_class,
    **items
  }
  plistlib.dump(d, dst_file)


def trim_import_statement(statement):
  m = re.match(r'\s*import (\w+)', statement)
  if not m: raise ValueError(f'egrep found bad import line: {statement!r}')
  return m[1]


system_frameworks = {
  'AVFoundation',
  'Accelerate',
  'AppKit',
  'CloudKit',
  'Contacts',
  'Core',
  'CoreAudio',
  'CoreData',
  'CoreFoundation',
  'CoreGraphics',
  'CoreImage',
  'CoreLocation',
  'CoreMedia',
  'CryptoTokenKit',
  'Darwin',
  'Dispatch',
  'Foundation',
  'GLKit',
  'GameplayKit',
  'IOKit',
  'Intents',
  'MapKit',
  'Metal',
  'MetalKit',
  'ModelIO',
  'ObjectiveC',
  'OpenCL',
  'QuartzCore',
  'RemoteMirror',
  'SafariServices',
  'SceneKit',
  'SpriteKit',
  'SwiftOnoneSupport',
  'Vision',
  'XCTest',
  'XPC',
  'os',
  'simd',
}

required_libs = { # TODO: unsure about this.
  'os',
  'ObjectiveC'
}

debug_libs = { # TODO: release libs.
  'RemoteMirror', # TODO: necessary?
  'SwiftOnoneSupport'
}


if __name__ == '__main__': main()