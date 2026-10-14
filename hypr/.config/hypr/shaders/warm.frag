#version 300 es
// Blue-light filter applied as a Hyprland screen shader.
// Unlike hyprsunset (per-output CTM), this also reaches mirrored outputs.
//
// A mirror receives the source monitor's already-shaded frame and then runs the
// screen shader again, so tinting it too would double the effect. TINT_OUTPUT
// is filled in by ~/.scripts/toggleHyprsunset.sh with the non-mirror monitor IDs.
precision highp float;

#define TINT_OUTPUT true

in vec2 v_texcoord;
uniform sampler2D tex;
uniform int wl_output;
layout(location = 0) out vec4 fragColor;

const float TEMPERATURE = 5000.0; // Kelvin; lower = warmer

vec3 kelvinToRgb(float k) {
    float t = k / 100.0;
    vec3 c;
    c.r = t <= 66.0 ? 1.0 : clamp(1.2929 * pow(t - 60.0, -0.1332), 0.0, 1.0);
    c.g = t <= 66.0 ? clamp(0.3901 * log(t) - 0.6318, 0.0, 1.0)
                    : clamp(1.1298 * pow(t - 60.0, -0.0755), 0.0, 1.0);
    c.b = t >= 66.0 ? 1.0 : (t <= 19.0 ? 0.0 : clamp(0.5432 * log(t - 10.0) - 1.1963, 0.0, 1.0));
    return c;
}

void main() {
    vec4 px = texture(tex, v_texcoord);
    fragColor = (TINT_OUTPUT) ? vec4(px.rgb * kelvinToRgb(TEMPERATURE), px.a) : px;
}
