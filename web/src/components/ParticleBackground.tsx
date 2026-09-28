import { useEffect, useRef } from 'react'
import { HeroKnot } from './HeroKnot'

type Mode = 'idle' | 'focus'

const VERTEX_SHADER = `#version 300 es
layout(location = 0) in vec2 a_position;
out vec2 vUv;
void main() {
  vUv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}`

// Recovered from Harness's WebGL2 background shader. The flowmap pass below
// supplies the same mouse-influence texture used by the original page.
const BACKGROUND_SHADER = `#version 300 es
precision mediump float;
in vec2 vUv;
uniform float u_time;
uniform vec2 u_resolution;
uniform vec3 u_c1, u_c2, u_c3, u_c4, u_c5;
uniform float u_scale;
uniform vec2 u_offset;
uniform float u_grain;
uniform float u_speed;
uniform sampler2D u_flowmap;
uniform float u_distortBoost;
uniform float u_swirlBoost;
uniform float u_glowIntensity;
uniform vec3 u_glowColor1;
uniform vec3 u_glowColor2;
uniform vec3 u_glowColor3;
uniform vec2 u_lightPos;
uniform float u_lightCore;
uniform float u_lightHalo;
uniform float u_vignette;
uniform float u_bloomThreshold;
uniform float u_bloomRange;
uniform float u_bloomStrength;
out vec4 fragColor;

vec3 mod289v3(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289v4(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289v4(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-.85373472095314*r;}

float snoise(vec3 v){
  const vec2 C=vec2(1./6.,1./3.);
  const vec4 D=vec4(0.,.5,1.,2.);
  vec3 i=floor(v+dot(v,C.yyy));
  vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);
  vec3 l=1.-g;
  vec3 i1=min(g.xyz,l.zxy);
  vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;
  vec3 x2=x0-i2+C.yyy;
  vec3 x3=x0-D.yyy;
  i=mod289v3(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
  float n_=.142857142857;
  vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z);
  vec4 y_=floor(j-7.*x_);
  vec4 x=x_*ns.x+ns.yyyy;
  vec4 y=y_*ns.x+ns.yyyy;
  vec4 h=1.-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);
  vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.+1.;
  vec4 s1=floor(b1)*2.+1.;
  vec4 sh=-step(h,vec4(0.));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;
  vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);
  vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);
  m=m*m;
  return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}

float hash(vec2 p){
  vec3 p3=fract(vec3(p.xyx)*.1031);
  p3+=dot(p3,p3.yzx+33.33);
  return fract((p3.x+p3.y)*p3.z);
}

float fbm(vec3 p){
  float v=0.,amp=.6;vec3 shift=vec3(100.);
  for(int i=0;i<1;i++){v+=amp*snoise(p);p=p*2.+shift;amp*=.4;}
  return v;
}

float fluidNoise(vec2 uv,float t){
  float n1=fbm(vec3(uv*.6,t*.06));
  float n2=fbm(vec3(uv*.6+5.2,t*.06+1.3));
  vec2 w1=vec2(n1,n2)*.6;
  float n3=fbm(vec3((uv+w1)*.7+1.7,t*.05+3.1));
  float n4=fbm(vec3((uv+w1)*.7+9.2,t*.05+5.7));
  vec2 w2=vec2(n3,n4)*.5;
  return fbm(vec3((uv+w1+w2)*.5,t*.04));
}

vec2 curlish(vec2 uv,float t){
  float eps=.02;
  float n=snoise(vec3(uv*.8,t));
  float nx=snoise(vec3((uv+vec2(eps,0.))*.8,t));
  float ny=snoise(vec3((uv+vec2(0.,eps))*.8,t));
  return vec2(-(ny-n)/eps,(nx-n)/eps)*.003;
}

void main(){
  float aspect=u_resolution.x/u_resolution.y;
  vec2 uv=gl_FragCoord.xy/u_resolution;
  vec2 suv=vec2(uv.x*aspect, uv.y) * u_scale + u_offset;
  float t=u_time;

  // Mouse interaction via flowmap
  vec4 flow = texture(u_flowmap, uv);
  float influence = flow.r;
  vec2 flowDir = (flow.gb - 0.5) * 2.0;

  // Apply mouse distortion to UV
  suv += flowDir * influence * u_distortBoost * 0.8;
  // Apply mouse swirl
  float swirlAngle = influence * u_swirlBoost * 2.5;
  float cs = cos(swirlAngle), sn = sin(swirlAngle);
  vec2 delta = suv - vec2(uv.x * aspect, uv.y) * u_scale;
  suv += (mat2(cs, sn, -sn, cs) * delta - delta) * influence;

  vec2 curl=curlish(suv,t*.04);
  vec2 uvD=suv+curl*12.;
  float f=fluidNoise(uvD,t);
  float swirl=snoise(vec3(uvD*.8+f*1.5,t*.035))*.5+.5;
  float n=f*.5+.5;
  vec3 col=mix(u_c1,u_c2,smoothstep(.2,.5,n));
  col=mix(col,u_c3,smoothstep(.35,.65,n+swirl*.25));
  col=mix(col,u_c4,smoothstep(.6,.85,swirl)*.55);
  col=mix(col,u_c5,smoothstep(.5,.8,n*swirl)*.35);

  // Mouse proximity color shift: 3-color glow blended by distance + noise
  float glow = smoothstep(0.0, 0.8, influence);
  float glowNoise = snoise(vec3(uvD * 1.5, t * 0.08)) * 0.5 + 0.5;
  float glowDist = smoothstep(0.0, 1.0, influence);
  vec3 glowMix = mix(u_glowColor3, u_glowColor2, glowDist);
  glowMix = mix(glowMix, u_glowColor1, glowDist * glowNoise);
  col = mix(col, glowMix, glow * u_glowIntensity);

  if(u_grain>0.0){
    vec2 flowOffset = (uvD - suv) * u_resolution.y;
    vec2 gp = floor((gl_FragCoord.xy + flowOffset) / 5.0);
    float gr=hash(gp)*2.-1.;
    col+=gr*u_grain;
  }

  // Self-luminance bloom: bright fluid regions become their own light spots,
  // so glow follows the flow and mouse disturbance instead of a fixed point
  float luma=dot(col,vec3(.299,.587,.114));
  float bloom=smoothstep(u_bloomThreshold-u_bloomRange,u_bloomThreshold+u_bloomRange,luma);
  col+=(col*.85+vec3(.15,.145,.13))*bloom*u_bloomStrength;

  // Virtual light source: soft warm core (same side as helm lighting)
  float ld=length((uv-u_lightPos)*vec2(aspect,1.));
  float core=exp(-ld*ld*4.5);
  float halo=exp(-ld*1.8);
  col+=vec3(1.,.97,.9)*core*u_lightCore+vec3(.72,.8,1.)*halo*u_lightHalo;

  float vig=1.-smoothstep(.35,.75,length(uv-.5));
  col=mix(col*(1.-u_vignette),col,vig);
  fragColor=vec4(col,1.);
}
`

const FLOW_SHADER = `#version 300 es
precision mediump float;
in vec2 vUv;
uniform sampler2D u_prev;
uniform vec2 u_mouse;
uniform vec2 u_velocity;
uniform float u_brushRadius;
uniform float u_brushStrength;
uniform float u_decay;
out vec4 fragColor;
void main() {
  vec4 prev = texture(u_prev, vUv);
  prev.r *= u_decay;
  prev.gb = mix(vec2(0.5), prev.gb, u_decay);
  float dist = distance(vUv, u_mouse);
  float influence = exp(-dist * dist / (u_brushRadius * u_brushRadius * 0.5));
  influence = max(0.0, influence - 0.01);
  float speed = length(u_velocity);
  float presenceStrength = u_brushStrength * 0.3;
  float velBonus = min(speed * 3.0, 0.7) * u_brushStrength;
  float totalStrength = presenceStrength + velBonus;
  prev.r = max(prev.r, influence * totalStrength);
  float blendAmt = influence * min(totalStrength, 0.4) * 0.3;
  prev.g = mix(prev.g, clamp(u_velocity.x * 2.0 + 0.5, 0.0, 1.0), blendAmt);
  prev.b = mix(prev.b, clamp(u_velocity.y * 2.0 + 0.5, 0.0, 1.0), blendAmt);
  fragColor = prev;
}`

function compile(gl: WebGL2RenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)
  if (!shader) throw new Error('Unable to create shader')
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) || 'Unknown shader error'
    gl.deleteShader(shader)
    throw new Error(message)
  }
  return shader
}

function program(gl: WebGL2RenderingContext, fragment: string) {
  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER)
  const frag = compile(gl, gl.FRAGMENT_SHADER, fragment)
  const result = gl.createProgram()
  if (!result) throw new Error('Unable to create program')
  gl.attachShader(result, vertex)
  gl.attachShader(result, frag)
  gl.linkProgram(result)
  gl.deleteShader(vertex)
  gl.deleteShader(frag)
  if (!gl.getProgramParameter(result, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(result) || 'Unable to link program')
  }
  return result
}

function rgb(hex: string) {
  const value = Number.parseInt(hex.slice(1), 16)
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255]
}

export function ParticleBackground({ mode = 'idle' }: { mode?: Mode }) {
  const root = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const gridCanvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const host = root.current
    const element = gridCanvas.current
    if (!host || !element) return
    const context = element.getContext('2d')
    if (!context) return

    type Particle = { restX: number; restY: number; x: number; y: number; vx: number; vy: number }
    let particles: Particle[] = []
    let columns = 0
    let rows = 0
    let width = 0
    let height = 0
    let raf = 0
    let last = 0
    let active = true
    const pointer = { x: Number.NaN, y: Number.NaN }
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    const rebuild = () => {
      width = host.clientWidth
      height = host.clientHeight
      element.width = Math.max(1, Math.round(width * dpr))
      element.height = Math.max(1, Math.round(height * dpr))
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      columns = Math.ceil(width / 90) + 1
      rows = Math.ceil(height / 90) + 1
      const offsetX = (width - (columns - 1) * 90) / 2
      const offsetY = (height - (rows - 1) * 90) / 2
      particles = []
      for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns; column += 1) {
          const x = offsetX + column * 90
          const y = offsetY + row * 90
          particles.push({ restX: x, restY: y, x, y, vx: 0, vy: 0 })
        }
      }
    }

    const onPointerMove = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect()
      pointer.x = event.clientX - rect.left
      pointer.y = event.clientY - rect.top
    }

    const render = (now: number) => {
      if (!active) { raf = requestAnimationFrame(render); return }
      if (now - last < 1000 / 30) { raf = requestAnimationFrame(render); return }
      last = now - (now - last) % (1000 / 30)
      if (width !== host.clientWidth || height !== host.clientHeight) rebuild()
      context.clearRect(0, 0, width, height)

      const lineColor = 'rgba(255, 255, 255, 0.08)'
      const dotColor = 'rgba(255, 255, 255, 0.16)'
      const mouseX = pointer.x
      const mouseY = pointer.y
      let maxVelocity = 0
      for (const particle of particles) {
        const dx = particle.x - mouseX
        const dy = particle.y - mouseY
        const distance = Math.sqrt(dx * dx + dy * dy)
        if (distance < 140 && distance > 0.1) {
          const force = (1 - distance / 140) * 30
          particle.vx += (dx / distance) * force * 0.1
          particle.vy += (dy / distance) * force * 0.1
        }
        particle.vx += (particle.restX - particle.x) * 0.05
        particle.vy += (particle.restY - particle.y) * 0.05
        particle.vx *= 0.85
        particle.vy *= 0.85
        particle.x += particle.vx
        particle.y += particle.vy
        maxVelocity = Math.max(maxVelocity, Math.abs(particle.vx) + Math.abs(particle.vy))
      }

      context.strokeStyle = lineColor
      context.lineWidth = 0.5
      for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns - 1; column += 1) {
          const current = particles[row * columns + column]
          const next = particles[row * columns + column + 1]
          const dx = next.x - current.x
          const dy = next.y - current.y
          const distance = Math.sqrt(dx * dx + dy * dy)
          if (distance < 20) continue
          context.beginPath()
          context.moveTo(current.x + (dx / distance) * 10, current.y + (dy / distance) * 10)
          context.lineTo(next.x - (dx / distance) * 10, next.y - (dy / distance) * 10)
          context.stroke()
        }
      }
      for (let column = 0; column < columns; column += 1) {
        for (let row = 0; row < rows - 1; row += 1) {
          const current = particles[row * columns + column]
          const next = particles[(row + 1) * columns + column]
          const dx = next.x - current.x
          const dy = next.y - current.y
          const distance = Math.sqrt(dx * dx + dy * dy)
          if (distance < 20) continue
          context.beginPath()
          context.moveTo(current.x + (dx / distance) * 10, current.y + (dy / distance) * 10)
          context.lineTo(next.x - (dx / distance) * 10, next.y - (dy / distance) * 10)
          context.stroke()
        }
      }

      context.fillStyle = dotColor
      for (const particle of particles) {
        let size = 1.8
        let alpha = 1
        if (!Number.isNaN(mouseX) && !Number.isNaN(mouseY)) {
          const dx = particle.x - mouseX
          const dy = particle.y - mouseY
          const influence = Math.max(0, 1 - Math.sqrt(dx * dx + dy * dy) / 140)
          size = 1.8 + 2 * influence
          alpha = 1 + 0.4 * influence
        }
        context.globalAlpha = alpha
        context.fillRect(particle.x - size, particle.y - size, size * 2, size * 2)
      }
      context.globalAlpha = 1
      raf = maxVelocity < 0.01 ? requestAnimationFrame(render) : requestAnimationFrame(render)
    }

    rebuild()
    window.addEventListener('pointermove', onPointerMove, { passive: true })
    const observer = new IntersectionObserver(([entry]) => { active = entry.isIntersecting })
    observer.observe(host)
    raf = requestAnimationFrame(render)
    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      window.removeEventListener('pointermove', onPointerMove)
    }
  }, [])

  useEffect(() => {
    const host = root.current
    const element = canvas.current
    if (!host || !element) return
    const gl = element.getContext('webgl2', { alpha: true, premultipliedAlpha: false, antialias: false, powerPreference: 'low-power' })
    if (!gl) {
      host.classList.add('particle-bg-fallback')
      return
    }

    let background: WebGLProgram
    let flow: WebGLProgram
    try {
      background = program(gl, BACKGROUND_SHADER)
      flow = program(gl, FLOW_SHADER)
    } catch (error) {
      console.error('[ParticleBackground] WebGL shader initialization failed', error)
      host.classList.add('particle-bg-fallback')
      return
    }

    const quad = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, quad)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const vao = gl.createVertexArray()
    gl.bindVertexArray(vao)
    gl.enableVertexAttribArray(0)
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0)

    const flowWidth = Math.max(1, Math.round(host.clientWidth * Math.min(window.devicePixelRatio || 1, 1.5) / 4))
    const flowHeight = Math.max(1, Math.round(host.clientHeight * Math.min(window.devicePixelRatio || 1, 1.5) / 4))
    const flowInitial = new Uint8Array(flowWidth * flowHeight * 4)
    for (let index = 0; index < flowInitial.length; index += 4) {
      flowInitial[index] = 0
      flowInitial[index + 1] = 128
      flowInitial[index + 2] = 128
      flowInitial[index + 3] = 255
    }
    const flowTextures = [0, 1].map(() => {
      const texture = gl.createTexture()!
      gl.bindTexture(gl.TEXTURE_2D, texture)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, flowWidth, flowHeight, 0, gl.RGBA, gl.UNSIGNED_BYTE, flowInitial)
      return texture
    })
    const flowFramebuffers = flowTextures.map((texture) => {
      const framebuffer = gl.createFramebuffer()!
      gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer)
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0)
      return framebuffer
    })
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)

    const bgLocations = Object.fromEntries(['u_time','u_resolution','u_c1','u_c2','u_c3','u_c4','u_c5','u_scale','u_offset','u_grain','u_speed','u_flowmap','u_distortBoost','u_swirlBoost','u_glowIntensity','u_glowColor1','u_glowColor2','u_glowColor3','u_lightPos','u_lightCore','u_lightHalo','u_vignette','u_bloomThreshold','u_bloomRange','u_bloomStrength'].map((name) => [name, gl.getUniformLocation(background, name)]))
    const flowLocations = Object.fromEntries(['u_prev','u_mouse','u_velocity','u_brushRadius','u_brushStrength','u_decay'].map((name) => [name, gl.getUniformLocation(flow, name)]))
    const colors = ['#000000', '#1A3870', '#204a7e', '#eed8aa', '#000000'].map(rgb)
    const glow = ['#fff7d1', '#538dca', '#2d448b'].map(rgb)
    let width = 1
    let height = 1
    let front = 0
    let raf = 0
    let visible = true
    const startedAt = performance.now()
    let last = startedAt
    const mouse = { x: 0.5, y: 0.5, tx: 0.5, ty: 0.5, vx: 0, vy: 0 }

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
      width = Math.max(1, host.clientWidth)
      height = Math.max(1, host.clientHeight)
      element.width = Math.floor(width * dpr)
      element.height = Math.floor(height * dpr)
      element.style.width = `${width}px`
      element.style.height = `${height}px`
      gl.viewport(0, 0, element.width, element.height)
    }
    const pointer = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect()
      mouse.tx = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
      mouse.ty = 1 - Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
    }
    const draw = (now: number) => {
      if (!visible || document.hidden) return
      const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000))
      last = now
      const dx = mouse.tx - mouse.x
      const dy = mouse.ty - mouse.y
      mouse.x += dx * 0.12
      mouse.y += dy * 0.12
      mouse.vx = dx / dt
      mouse.vy = dy / dt

      const back = 1 - front
      gl.bindVertexArray(vao)
      gl.useProgram(flow)
      gl.bindFramebuffer(gl.FRAMEBUFFER, flowFramebuffers[back])
      gl.viewport(0, 0, flowWidth, flowHeight)
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, flowTextures[front])
      gl.uniform1i(flowLocations.u_prev, 0)
      gl.uniform2f(flowLocations.u_mouse, mouse.x, mouse.y)
      gl.uniform2f(flowLocations.u_velocity, mouse.vx, mouse.vy)
      gl.uniform1f(flowLocations.u_brushRadius, 0.09)
      gl.uniform1f(flowLocations.u_brushStrength, 1.8)
      gl.uniform1f(flowLocations.u_decay, 0.925)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      front = back

      gl.bindFramebuffer(gl.FRAMEBUFFER, null)
      gl.viewport(0, 0, element.width, element.height)
      gl.useProgram(background)
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, flowTextures[front])
      gl.uniform1i(bgLocations.u_flowmap, 0)
      gl.uniform1f(bgLocations.u_time, (now - startedAt) * 0.001 * (28 / 100))
      gl.uniform2f(bgLocations.u_resolution, element.width, element.height)
      gl.uniform1f(bgLocations.u_scale, 1.77)
      gl.uniform2f(bgLocations.u_offset, -124 / 100, -48 / 100)
      gl.uniform1f(bgLocations.u_grain, 0.005)
      gl.uniform1f(bgLocations.u_speed, 28)
      gl.uniform1f(bgLocations.u_distortBoost, 2.2)
      gl.uniform1f(bgLocations.u_swirlBoost, 0.8)
      gl.uniform1f(bgLocations.u_glowIntensity, 0.13)
      gl.uniform2f(bgLocations.u_lightPos, 0.89, 0.46)
      gl.uniform1f(bgLocations.u_lightCore, 0.14)
      gl.uniform1f(bgLocations.u_lightHalo, 0.2)
      gl.uniform1f(bgLocations.u_vignette, 0.38)
      gl.uniform1f(bgLocations.u_bloomThreshold, 0.61)
      gl.uniform1f(bgLocations.u_bloomRange, 0.18)
      gl.uniform1f(bgLocations.u_bloomStrength, 0.4)
      colors.forEach((color, index) => gl.uniform3f(bgLocations[`u_c${index + 1}`], color[0], color[1], color[2]))
      glow.forEach((color, index) => gl.uniform3f(bgLocations[`u_glowColor${index + 1}`], color[0], color[1], color[2]))
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      raf = requestAnimationFrame(draw)
    }

    resize()
    window.addEventListener('resize', resize)
    host.addEventListener('pointermove', pointer)
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible && !raf) { last = performance.now(); raf = requestAnimationFrame(draw) } }, { threshold: 0 })
    observer.observe(host)
    raf = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      window.removeEventListener('resize', resize)
      host.removeEventListener('pointermove', pointer)
      flowFramebuffers.forEach((framebuffer) => gl.deleteFramebuffer(framebuffer))
      flowTextures.forEach((texture) => gl.deleteTexture(texture))
      gl.deleteProgram(background)
      gl.deleteProgram(flow)
      gl.deleteBuffer(quad)
      gl.deleteVertexArray(vao)
    }
  }, [mode])

  return (
    <div ref={root} className={`particle-bg particle-bg-${mode}`} aria-hidden="true">
      <canvas ref={canvas} className="particle-bg-fluid" />
      <HeroKnot center />
      <canvas ref={gridCanvas} className="particle-bg-grid" />
      <div className="particle-bg-glow particle-bg-glow-left" />
      <div className="particle-bg-glow particle-bg-glow-center" />
      <div className="particle-bg-glow particle-bg-glow-right" />
    </div>
  )
}










