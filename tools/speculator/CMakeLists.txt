# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

add_hermes_tool(speculator speculator.cpp
  ../shermes/ParseJSFile.cpp ../shermes/ParseJSFile.h
  LINK_OBJLIBS hermesSpeculator_obj
  LINK_LIBS hermescompiler)
