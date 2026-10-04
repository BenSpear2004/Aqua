// Reproducible static projection of the supplied asset, for loading and WebGL failures.
// This does not alter the GLB or invent a replacement mark.
import fs from "node:fs";
import { Box3, Color, Vector3 } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const input = new URL("../src/assets/models/Aqua_logo.glb", import.meta.url);
const output = new URL("../src/assets/models/Aqua_logo_static.svg", import.meta.url);
const bytes = fs.readFileSync(input);
const gltf = await new GLTFLoader().parseAsync(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), "");
const scene = gltf.scenes.find((item) => item.name === "AQUA_Logo") ?? gltf.scene;
scene.updateMatrixWorld(true);
const bounds = new Box3().setFromObject(scene);
const size = bounds.getSize(new Vector3());
const scale = 500 / size.y;
const width = Math.ceil(size.x * scale + 24);
const height = 524;
const direction = new Vector3(-0.45, 0.7, 1).normalize();
const triangles = [];
scene.traverse((mesh) => {
  if (!mesh.isMesh) return;
  const positions = mesh.geometry.attributes.position;
  const index = mesh.geometry.index;
  const count = index ? index.count : positions.count;
  const material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
  for (let offset = 0; offset < count; offset += 3) {
    const points = [0, 1, 2].map((vertex) => new Vector3().fromBufferAttribute(positions, index ? index.getX(offset + vertex) : offset + vertex).applyMatrix4(mesh.matrixWorld));
    const normal = new Vector3().subVectors(points[1], points[0]).cross(new Vector3().subVectors(points[2], points[0])).normalize();
    if (normal.z <= 0.015) continue;
    const diffuse = 0.64 + 0.58 * Math.max(0, normal.dot(direction));
    const color = new Color().copy(material.color).multiplyScalar(Math.round(diffuse * 8) / 8);
    if (material.emissive) color.add(material.emissive);
    const coordinates = points.map((point) => `${((point.x - bounds.min.x) * scale + 12).toFixed(1)} ${((bounds.max.y - point.y) * scale + 12).toFixed(1)}`);
    triangles.push({ depth: points.reduce((sum, point) => sum + point.z, 0) / 3, color: `#${color.getHexString()}`, path: `M${coordinates[0]}L${coordinates[1]}L${coordinates[2]}Z` });
  }
});
triangles.sort((a, b) => a.depth - b.depth);
const paths = [];
let previous;
for (const triangle of triangles) {
  if (previous?.color === triangle.color) previous.path += triangle.path;
  else {
    previous = { color: triangle.color, path: triangle.path };
    paths.push(previous);
  }
}
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="AQUA"><title>Static projection of the supplied AQUA logo</title>${paths.map((item) => `<path fill="${item.color}" d="${item.path}"/>`).join("")}</svg>`;
fs.writeFileSync(output, svg);
console.log(`Created ${output.pathname.split("/").at(-1)} from ${triangles.length} visible source triangles (${Buffer.byteLength(svg)} bytes).`);
