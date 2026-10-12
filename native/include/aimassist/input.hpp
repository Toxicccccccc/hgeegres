#pragma once

#include <string>

namespace aimassist
{
// Resolve a binding name to a Windows virtual-key code once. 0 means "no key"
// ("Auto" or an unrecognised name).
int resolve_input_key(std::string const& input_name);

// Poll a pre-resolved virtual key. The per-frame loop uses this instead of
// input_is_pressed(): parsing the binding string (a heap copy, a lowercase pass
// and a hash lookup) on every one of the hundreds of frames per second was pure
// waste, and the parsed code never changes while the engine runs. The physical
// key state is still read fresh each frame, so responsiveness is unchanged.
bool input_is_pressed_vk(int virtual_key);

// Convenience: resolve + poll in one call. Used where a single check per frame
// is enough and caching is not worth it.
bool input_is_pressed(std::string const& input_name);
} // namespace aimassist
