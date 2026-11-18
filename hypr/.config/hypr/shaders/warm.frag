#version 300 es
// Blue-light filter applied as a Hyprland screen shader.
// Unlike hyprsunset (per-output CTM), this also reaches mirrored outputs.
//
// Every screen is tinted, mirrors too: since Hyprland 0.57.1 a mirror gets the
// source's frame without the shader and runs the shader itself. (Up to 0.57.0
// it got the tinted frame, so the tint was limited to non-mirrors then; if a
// mirror ever looks warmer than the laptop, that's back.)
precision highp float;

in vec2 v_texcoord;
uniform sampler2D tex;
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
    fragColor = vec4(px.rgb * kelvinToRgb(TEMPERATURE), px.a);
}
