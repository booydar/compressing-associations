# === Inlined ARMT for HF Hub (single-file) ===

# ---- language_modeling.py ----
import math
import torch
from torch.nn import CrossEntropyLoss
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions
from transformers.cache_utils import Cache, DynamicCache
from torch.nn.functional import relu as r
import torch.nn.functional as F
from munch import Munch
import os

try:
    from baselines.rwkv.language_modeling import RWKVModel
    RWKV_imported = True
except ImportError:
    print("*** Can't import RWKV model ***")
    RWKV_imported = False


def attn_mask_to_4d(attn_mask, upper, query_len):
    if attn_mask is None:
        return None
    seg_len = attn_mask.size(-1)
    if upper:
        tri = torch.triu(torch.ones(query_len, seg_len))
    else:
        tri = torch.tril(torch.ones(query_len, seg_len))
    mask = torch.einsum('bj,ij->bij', attn_mask, tri.to(attn_mask.device))
    mask = mask.unsqueeze(1)
    return mask


def invert_attn_mask(attn_mask, dtype):
    min_dtype = torch.finfo(dtype).min
    new_mask = (1.0 - attn_mask) * min_dtype
    return new_mask


class DPFP:
    def __init__(self, nu):
        self.nu = nu

    def __call__(self, x):
        nu = self.nu
        x = torch.cat([r(x), r(-x)], dim=-1)
        x_rolled = torch.cat([x.roll(shifts=j, dims=-1) for j in range(1, nu+1)], dim=-1)
        x_repeat = torch.cat([x] * nu, dim=-1)
        return x_repeat * x_rolled


class AssociativeLayerWrapper(torch.nn.Module):

    def __init__(self, layer, d_model, num_mem_tokens, d_mem, n_heads=1, correction=True, info=None, use_denom=True, gating=False) -> None:
        super().__init__()
        self.info = info
        self.seg_num = 0
        self.d_model = d_model
        self.num_mem_tokens = num_mem_tokens
        self.d_mem = d_mem
        self.n_heads = n_heads
        self.gating = gating
        nu = 3
        self.d_key = 2 * nu * d_mem

        assert self.d_mem % n_heads == 0 and self.d_model % n_heads == 0

        self.phi = DPFP(nu)
        self.use_denom = use_denom

        layer_dtype = next(layer.parameters()).dtype

        self.W_mq = torch.nn.Linear(d_model, d_mem, bias=False, dtype=layer_dtype)
        self.W_mk = torch.nn.Linear(d_model, d_mem, bias=False, dtype=layer_dtype)
        self.W_mv = torch.nn.Linear(d_model, d_model, bias=False, dtype=layer_dtype)
        if gating:
            self.W_mb = torch.nn.Linear(d_model, d_model, dtype=layer_dtype)
        else:
            self.W_mb = torch.nn.Linear(d_model, n_heads, dtype=layer_dtype)
        torch.nn.init.zeros_(self.W_mv.weight)

        self.layer = layer
        self.generate_mode = False
        self.first_seg = True
        self.correction = correction

        self.zero_mem()

    def _to_heads(self, x):
        bsz, seq_len, d_model = x.shape
        x = x.reshape(bsz, seq_len, self.n_heads, d_model // self.n_heads)
        x = x.permute(0, 2, 1, 3)
        return x

    def _from_heads(self, x):
        bsz, n_heads, seq_len, d_head = x.shape
        x = x.permute(0, 2, 1, 3).reshape(bsz, seq_len, n_heads * d_head)
        return x

    def associate(self, hidden_states):
        bsz, seq_len, d_model = hidden_states.shape

        self.W_mem = self.W_mem.to(hidden_states.device)
        if self.use_denom:
            self.z = self.z.to(hidden_states.device)

        q = self._to_heads(self.W_mq(hidden_states))
        mq = self.phi(q)
        mq = F.normalize(mq, dim=-1, p=2.0)
        num = torch.einsum('ihjk,ihkt->ihjt', mq, self.W_mem)
        if self.use_denom:
            denom = torch.einsum("ihk,ihjk->ihj", self.z, mq)[..., None] + 1e-5
            hidden_states = num / denom
        else:
            hidden_states = num
        hidden_states = self._from_heads(hidden_states)
        return hidden_states

    def forward(self, hidden_states, *args, **kwargs):
        if not self.first_seg:
            hidden_states = self.associate(hidden_states) + hidden_states
        out = self.layer(hidden_states, *args, **kwargs)
        if not self.generate_mode:
            if isinstance(out, tuple):
                mem_tokens = out[0][:, -self.num_mem_tokens:]
            else:
                mem_tokens = out[:, -self.num_mem_tokens:]
            self.update_mem(mem_tokens)
        return out

    def forward_no_update(self, hidden_states, *args, **kwargs):
        if not self.first_seg:
            hidden_states = self.associate(hidden_states) + hidden_states
        out = self.layer(hidden_states, *args, **kwargs)
        return out

    def update_mem(self, mem_tokens):
        self.W_mem = self.W_mem.to(mem_tokens.device)
        if self.use_denom:
            self.z = self.z.to(mem_tokens.device)
        k = self._to_heads(self.W_mk(mem_tokens))
        mk = self.phi(k)
        mk = F.normalize(mk, dim=-1, p=2.0)

        new_mv = self._to_heads(self.W_mv(mem_tokens))
        if not self.first_seg:
            num = torch.einsum('ihjk,ihkt->ihjt', mk, self.W_mem)
            if self.use_denom:
                denom = torch.einsum("ihj,ihkj->ihk", self.z, mk)[..., None] + 1e-5
                prev_mv = num / denom
                if self.correction:
                    new_info_coef = (1 - denom / (torch.linalg.norm(mk, dim=-1) ** 2)[..., None])
                    new_info_coef = torch.clip(new_info_coef, 0, 1).detach()
                else:
                    new_info_coef = 1
            else:
                prev_mv = num
        else:
            prev_mv = torch.zeros_like(new_mv, device=new_mv.device)
            new_info_coef = 1

        mv = new_mv - prev_mv
        mb = self._to_heads(torch.sigmoid(self.W_mb(mem_tokens)))

        einop = f"ihjk,ihjt,ihj{'t' if self.gating else 'x'}->ihkt"
        associations = torch.einsum(einop, mk, mv, mb)

        self.W_mem = self.W_mem + associations

        if self.use_denom:
            self.z = self.z + (new_info_coef * mk).sum(dim=-2)
        self.seg_num += 1
        self.first_seg = False

    def freeze_mem(self):
        self.W_mb.weight.requires_grad = False
        self.W_mb.bias.requires_grad = False
        self.W_mq.weight.requires_grad = False
        self.W_mk.weight.requires_grad = False
        self.W_mv.weight.requires_grad = False

    def zero_mem(self):
        self.first_seg = True
        layer_dtype = next(self.layer.parameters()).dtype
        self.W_mem = torch.zeros(1, self.n_heads, self.d_key // self.n_heads, self.d_model // self.n_heads, dtype=layer_dtype)
        self.W_mem.requires_grad_(False)
        if self.use_denom:
            self.z = torch.zeros(1, self.n_heads, self.d_key // self.n_heads, dtype=layer_dtype)
            self.z.requires_grad_(False)
        self.seg_num = 0

    def detach_mem(self):
        self.W_mem = self.W_mem.detach()
        if self.use_denom:
            self.z = self.z.detach()


class AssociativeMemoryCell(torch.nn.Module):
    def __init__(self,
                 base_model,
                 num_mem_tokens,
                 d_mem,
                 layers_attr: str = 'model.layers',
                 wrap_pos=False,
                 correction=True,
                 n_heads=1,
                 use_denom=True,
                 gating=False,
                 freeze_mem=False,
                 attend_to_previous_input=False,
                 use_sink=False,
                 **rmt_config
                 ):
        super().__init__()
        self.model = base_model

        self.attend_to_previous_input = attend_to_previous_input
        self.previous_input = None
        self.use_sink = use_sink

        self.RWKV_ARMT = isinstance(self.model, RWKVModel) if RWKV_imported else False

        self.num_mem_tokens = num_mem_tokens
        self.d_mem = d_mem
        self.d_model = base_model.get_input_embeddings().embedding_dim
        self.W_mem = []

        self.layers_attrs = layers_attr.split('.')

        def _get_layers_from_model(model_root):
            layers_obj = model_root
            for attr in self.layers_attrs:
                layers_obj = getattr(layers_obj, attr)
            return layers_obj

        layers = _get_layers_from_model(self.model)

        for i in range(len(layers)):
            kw = dict(
                layer=layers[i],
                d_model=self.d_model,
                num_mem_tokens=self.num_mem_tokens,
                d_mem=self.d_mem,
                correction=correction,
                info={'layer': i},
                n_heads=n_heads,
                use_denom=use_denom,
                gating=gating,
            )
            layers[i] = AssociativeLayerWrapper(**kw)

        self.create_memory(num_mem_tokens)
        self.wrap_pos = wrap_pos
        if wrap_pos:
            self.wrap_positional_embeddings(num_mem_tokens)

        if freeze_mem:
            for layer in _get_layers_from_model(self.model):
                layer.freeze_mem()

        self.get_layers = lambda: _get_layers_from_model(self.model)

    def generate_mode(self, is_on):
        for layer in self.get_layers():
            layer.generate_mode = is_on

    def create_memory(self, num_mem_tokens):
        self.num_mem_tokens = num_mem_tokens
        embeddings = self.model.get_input_embeddings()
        memory_dim = getattr(self.model.config, 'n_embd', self.model.config.hidden_size)
        memory_weights = torch.randn((num_mem_tokens, memory_dim), device=embeddings.weight.data.device, dtype=embeddings.weight.data.dtype) * embeddings.weight.data.std()
        self.register_parameter('memory', torch.nn.Parameter(memory_weights, requires_grad=True))
        if self.use_sink:
            self.sink = torch.nn.Parameter(torch.randn((1, memory_dim), device=embeddings.weight.data.device, dtype=embeddings.weight.data.dtype), requires_grad=True)

    def wrap_positional_embeddings(self, num_mem_tokens):
        num_pos_embs, emb_dim = self.model.transformer.wpe.weight.shape
        prev_embs = self.model.transformer.wpe.weight.detach()
        self.model.transformer.wpe = torch.nn.Embedding(num_mem_tokens + num_pos_embs, emb_dim)
        new_num_pos = num_pos_embs + num_mem_tokens
        with torch.no_grad():
            self.model.transformer.wpe.weight[:len(self.model.transformer.wpe.weight)-num_mem_tokens] = prev_embs
        for layer in self.model.transformer.h:
            layer.layer.attn.bias = torch.tril(torch.ones((new_num_pos, new_num_pos), dtype=torch.uint8)).view(
                1, 1, new_num_pos, new_num_pos
            )

    def set_memory(self, input_shape):
        memory = self.memory.repeat(input_shape[0], 1, 1)
        if self.use_sink:
            sink = self.sink.repeat(input_shape[0], 1, 1)
        else:
            sink = None
        return memory, sink

    def zero_mem(self):
        for layer in self.get_layers():
            layer.zero_mem()
        self.previous_input = None

    def detach_mem(self):
        for layer in self.get_layers():
            layer.detach_mem()

    def forward(self, input_ids, labels=None, labels_mask=None, zero_mem=False, attention_mask=None, **kwargs):
        return self.forward_with_update(input_ids, labels, labels_mask, zero_mem, attention_mask=attention_mask, **kwargs)

    def forward_with_update(self, input_ids, labels=None, labels_mask=None, zero_mem=False, **kwargs):
        current_input_ids = input_ids.clone()
        if self.attend_to_previous_input and self.previous_input is not None:
            input_ids = torch.cat([self.previous_input, input_ids], dim=1)

        if zero_mem:
            self.zero_mem()

        seg_kwargs = self.process_input(input_ids, **kwargs)

        layers = self.get_layers()
        if self.RWKV_ARMT and not layers[0].generate_mode:
            input1 = dict()
            input2 = dict()
            for item in seg_kwargs:
                if isinstance(seg_kwargs[item], torch.Tensor):
                    input1[item] = seg_kwargs[item][:, :-self.num_mem_tokens]
                    input2[item] = seg_kwargs[item][:, -self.num_mem_tokens:]
                else:
                    input1[item] = seg_kwargs[item]
                    input2[item] = seg_kwargs[item]

            self.generate_mode(True)
            out = self.model(**input1)
            self.generate_mode(False)
            state_tmp = tuple([torch.clone(state) for state in out['state']])
            out = Munch({k: torch.clone(t) if isinstance(t, torch.Tensor) else t for k, t in out.items()})
            input2['state'] = out['state']
            _ = self.model(**input2)
            out['state'] = state_tmp
        else:
            out = self.model(**seg_kwargs)

        if self.attend_to_previous_input and self.previous_input is not None:
            out['logits'] = out['logits'][:, self.previous_input.size(1):]
        out = self.process_output(out, labels, labels_mask, **kwargs)
        self.previous_input = current_input_ids
        return out

    def process_input(self, input_ids, **kwargs):
        memory_state, sink = self.set_memory(input_ids.shape)
        seg_kwargs = dict(**kwargs)
        inputs_embeds = kwargs.get('inputs_embeds')
        if inputs_embeds is None:
            inputs_embeds = self.model.get_input_embeddings()(input_ids)
        if self.use_sink:
            inputs_embeds = torch.cat([sink, inputs_embeds, memory_state], dim=1)
        else:
            inputs_embeds = torch.cat([inputs_embeds, memory_state], dim=1)

        seg_kwargs['input_ids'] = None
        seg_kwargs['inputs_embeds'] = inputs_embeds
        if kwargs.get('attention_mask') is not None:
            seg_kwargs['attention_mask'] = self.pad_attention_mask(kwargs['attention_mask'], dtype=inputs_embeds.dtype)
            if kwargs.get('prev_attn_mask') is not None:
                prev_seg_attn_mask = self.pad_prev_seg_attn_mask(kwargs['prev_attn_mask'], dtype=inputs_embeds.dtype)
                seg_kwargs['attention_mask'] = torch.cat([prev_seg_attn_mask, seg_kwargs['attention_mask']], dim=-1)
        if 'prev_attn_mask' in seg_kwargs:
            seg_kwargs.pop('prev_attn_mask')
        seg_kwargs['output_hidden_states'] = True

        if self.wrap_pos:
            num_pos_embs = self.model.transformer.wpe.weight.shape[0]
            ordinary_pos = torch.arange(0, input_ids.size(1), dtype=torch.long, device=input_ids.device)
            write_pos = torch.arange(num_pos_embs - self.num_mem_tokens, num_pos_embs, dtype=torch.long, device=input_ids.device)
            seg_kwargs['position_ids'] = torch.cat([ordinary_pos, write_pos]).long().unsqueeze(0)
        return seg_kwargs

    def pad_attention_mask(self, attention_mask, dtype=float):
        if self.num_mem_tokens in {0, None}:
            return attention_mask
        else:
            shape = list(attention_mask.shape)
            if len(shape) == 4:
                shape[-1] += self.num_mem_tokens + self.use_sink
                shape[-2] += self.num_mem_tokens + self.use_sink
                mask = torch.ones(*shape, dtype=dtype).to(attention_mask.device)
                mask[..., int(self.use_sink):-self.num_mem_tokens, int(self.use_sink):-self.num_mem_tokens] = attention_mask
                if self.use_sink:
                    mask[..., 0, 1:] = 0
                mask[..., :-self.num_mem_tokens, -self.num_mem_tokens:] = 0
                if not os.environ.get("NOT_INVERT_ATTN_MASK"):
                    mask = invert_attn_mask(mask, dtype)
            else:
                shape[-1] += self.num_mem_tokens + self.use_sink
                mask = torch.ones(*shape, dtype=dtype).to(attention_mask.device)
                mask[..., int(self.use_sink):-self.num_mem_tokens] = attention_mask
            return mask.to(dtype)

    def pad_prev_seg_attn_mask(self, prev_seg_attn_mask, dtype=float):
        if self.num_mem_tokens in {0, None}:
            return prev_seg_attn_mask
        else:
            shape = list(prev_seg_attn_mask.shape)
            if len(shape) == 4:
                shape[-2] += self.num_mem_tokens + self.use_sink
                mask = torch.ones(*shape, dtype=dtype).to(prev_seg_attn_mask.device)
                mask[..., int(self.use_sink):-self.num_mem_tokens, :] = prev_seg_attn_mask
                if self.use_sink:
                    mask[..., 0, :] = 0
                if not os.environ.get("NOT_INVERT_ATTN_MASK"):
                    mask = invert_attn_mask(mask, dtype)
            else:
                mask = prev_seg_attn_mask
            return mask.to(dtype)

    def process_output(self, model_outputs, labels, labels_mask, **kwargs):
        if (self.num_mem_tokens not in {0, None}) and not self.RWKV_ARMT:
            out = CausalLMOutputWithCrossAttentions()
            out['logits'] = model_outputs.logits[:, int(self.use_sink):-self.num_mem_tokens]
            if kwargs.get('output_hidden_states'):
                out['hidden_states'] = [lh[:, int(self.use_sink):-self.num_mem_tokens] for lh in model_outputs.hidden_states]
            if kwargs.get('output_attentions'):
                out['attentions'] = model_outputs['attentions']
        else:
            out = model_outputs

        if labels is not None:
            logits = out['logits'][..., :-1, :].contiguous()
            flat_logits = logits.view(-1, logits.size(-1))
            labels = labels[..., 1:].contiguous()
            flat_labels = labels.view(-1)
            if labels_mask is not None:
                flat_mask = labels_mask[..., :-1].contiguous().view(-1)
                flat_logits = flat_logits[flat_mask]
                flat_labels = flat_labels[flat_mask]

            ce_loss_fn = CrossEntropyLoss(reduction='sum')
            ce_loss = ce_loss_fn(flat_logits, flat_labels)
            if labels_mask is not None:
                denom = labels_mask[..., :-1].contiguous().view(-1).sum()
            else:
                denom = (flat_labels != -100).sum()
            denom = torch.clamp(denom, min=1)
            out['ce_loss'] = ce_loss / denom

        if kwargs.get('use_cache', False):
            out['past_key_values'] = model_outputs.past_key_values
        return out

    def generate(self, input_ids, attention_mask, zero_mem=False, **generate_kwargs):
        if zero_mem:
            self.zero_mem()
        self.generate_mode(True)
        seg_kwargs = self.process_input(input_ids, attention_mask=attention_mask)
        out = self.model.generate(
            inputs_embeds=seg_kwargs['inputs_embeds'][:, :-self.num_mem_tokens],
            attention_mask=seg_kwargs['attention_mask'][:, :-self.num_mem_tokens],
            **generate_kwargs
        )
        self.generate_mode(False)
        return out

    def update_past_key_values_sw(self, past_key_values, window_size):
        past_key_values = past_key_values.to_legacy_cache()
        past_key_values = [
            [
                k_or_v[..., -(window_size+self.use_sink):, :]
                for k_or_v in seg_kv
            ]
            for seg_kv in past_key_values
        ]
        past_key_values = DynamicCache.from_legacy_cache(past_key_values)
        return past_key_values

    def greedy_generate_sw(self, input_ids, attention_mask, prev_attn_mask, **generate_kwargs):
        self.generate_mode(True)
        window_size = generate_kwargs['window_size']
        max_new_tokens = generate_kwargs['max_new_tokens']
        past_key_values = self.update_past_key_values_sw(generate_kwargs['past_key_values'], window_size)
        eos_token_id = generate_kwargs['eos_token_id']
        prev_attn_mask_2d = prev_attn_mask.clone()
        attention_mask_2d = attention_mask.clone()

        attention_mask = attn_mask_to_4d(attention_mask, upper=False, query_len=attention_mask.size(-1))
        prev_attn_mask = attn_mask_to_4d(prev_attn_mask, upper=True, query_len=attention_mask.size(-1))
        seg_kwargs = self.process_input(input_ids=input_ids, attention_mask=attention_mask, prev_attn_mask=prev_attn_mask, past_key_values=past_key_values)
        seg_kwargs['inputs_embeds'] = seg_kwargs['inputs_embeds'][..., :-self.num_mem_tokens, :]
        seg_kwargs['attention_mask'] = seg_kwargs['attention_mask'][..., :-self.num_mem_tokens, :-self.num_mem_tokens]
        outputs = self.model(**seg_kwargs, use_cache=True)

        next_token_logits = outputs.logits[:, -1, :]
        past_key_values = outputs.past_key_values
        past_key_values = self.update_past_key_values_sw(past_key_values, window_size)

        generated_ids = None
        sw_attention_mask = torch.cat([prev_attn_mask_2d, torch.ones(attention_mask_2d.size(0), 1).to(prev_attn_mask_2d.device), attention_mask_2d], dim=-1)

        for i in range(max_new_tokens):
            next_token_id = torch.argmax(next_token_logits, dim=-1).unsqueeze(-1)

            if generated_ids is not None:
                generated_ids = torch.cat([generated_ids, next_token_id], dim=-1)
            else:
                generated_ids = next_token_id
            next_input = next_token_id

            sw_attention_mask = torch.cat([sw_attention_mask, torch.ones_like(next_token_id).to(sw_attention_mask.device)], dim=-1)[..., -window_size-1-self.use_sink:]
            with torch.no_grad():
                outputs = self.model(
                    input_ids=next_input,
                    attention_mask=sw_attention_mask,
                    past_key_values=past_key_values,
                    use_cache=True,
                    cache_position=torch.full((1,), window_size + i + input_ids.size(-1) + self.use_sink).to(input_ids.device)
                )
                past_key_values = self.update_past_key_values_sw(outputs.past_key_values, window_size)
                next_token_logits = outputs.logits[:, -1, :]

                if (next_token_id[:, 0] == eos_token_id).all():
                    break
        self.generate_mode(False)
        return generated_ids


class AssociativeRecurrentWrapper(torch.nn.Module):
    def __init__(self, memory_cell, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.rmt_config = rmt_kwargs
        self.last_state = None

    def gradient_checkpointing_enable(self, *args, **kwargs):
        self.memory_cell.model.gradient_checkpointing_enable(*args, **kwargs)

    def process_segment(self, segment_kwargs, next_seg_len=None):
        sliding_window = self.rmt_config['sliding_window'] if 'sliding_window' in self.rmt_config else False
        attend_to_previous_input = self.rmt_config['attend_to_previous_input'] if 'attend_to_previous_input' in self.rmt_config else False
        attn_mask = segment_kwargs['attention_mask']
        seg_len = segment_kwargs['input_ids'].size(-1)

        segment_kwargs['use_cache'] = sliding_window
        if segment_kwargs.get('past_key_values') is None:
            segment_kwargs['past_key_values'] = None
        if segment_kwargs.get('prev_attn_mask') is None:
            segment_kwargs['prev_attn_mask'] = None
        segment_kwargs['zero_mem'] = False
        if sliding_window or attend_to_previous_input:
            segment_kwargs['attention_mask'] = attn_mask_to_4d(attn_mask, upper=False, query_len=seg_len)

        if 'state' in segment_kwargs and segment_kwargs['state'] is None:
            segment_kwargs.pop('state')

        num_mem_tokens = self.memory_cell.num_mem_tokens
        cell_out = self.memory_cell(**segment_kwargs)
        state = cell_out.get('state')
        if (sliding_window or attend_to_previous_input) and next_seg_len is not None:
            prev_attn_mask = attn_mask_to_4d(attn_mask, upper=True, query_len=next_seg_len)
        else:
            prev_attn_mask = None
        if sliding_window:
            past_key_values = [
                [
                    k_or_v[..., -(num_mem_tokens+seg_len):k_or_v.size(-2)-num_mem_tokens, :].detach()
                    for k_or_v in seg_kv
                ]
                for seg_kv in cell_out['past_key_values']
            ]
            if not isinstance(cell_out['past_key_values'], tuple) and not isinstance(cell_out['past_key_values'], list):
                past_key_values = cell_out['past_key_values'].from_legacy_cache(past_key_values)
            else:
                past_key_values = DynamicCache.from_legacy_cache(past_key_values)
        else:
            past_key_values = None
        next_segment_kwargs = dict()
        next_segment_kwargs['use_cache'] = sliding_window
        next_segment_kwargs['past_key_values'] = past_key_values
        next_segment_kwargs['prev_attn_mask'] = prev_attn_mask
        next_segment_kwargs['zero_mem'] = False
        if state is not None:
            next_segment_kwargs['state'] = state
        return cell_out, next_segment_kwargs

    def forward(self,
                input_ids,
                labels=None,
                labels_mask=None,
                inputs_embeds=None,
                attention_mask=None,
                output_attentions=None,
                output_hidden_states=None,
                input_segmented=False,
                output_only_last_segment=False,
                use_previous_batch_state=torch.zeros(1),
                num_items_in_batch=None,
                **kwargs
                ):
        if input_segmented:
            n_segs = input_ids.shape[1] if not (input_ids is None) else inputs_embeds.shape[1]
            segmented = [dict(
                input_ids=input_ids[:, i] if not (input_ids is None) else None,
                inputs_embeds=inputs_embeds[:, i] if not (inputs_embeds is None) else None,
                attention_mask=attention_mask[:, i],
                labels=labels[:, i] if not (labels is None) else None,
                labels_mask=labels_mask[:, i] if not (labels_mask is None) else None,
            ) for i in range(n_segs)]
            labels = torch.cat([labels[:, i] for i in range(n_segs)], dim=1)
            if labels_mask is not None:
                labels_mask = torch.cat([labels_mask[:, i] for i in range(n_segs)], dim=1)
        else:
            segmented = self.segment(input_ids=input_ids, inputs_embeds=inputs_embeds, attention_mask=attention_mask, labels=labels, labels_mask=labels_mask)

        cell_outputs = []
        if not use_previous_batch_state.all() or self.last_state is None:
            self.memory_cell.zero_mem()
            state = None
        else:
            self.memory_cell.detach_mem()
            state = self.last_state
        next_seg_kwargs = dict(state=state)
        for seg_num, segment in enumerate(segmented):
            if seg_num != len(segmented) - 1:
                next_seg_len = segmented[seg_num + 1]['input_ids'].size(-1)
            else:
                next_seg_len = None
            segment_with_kwargs = dict(**segment, **next_seg_kwargs)
            if kwargs.get('num_items_in_batch') is not None:
                segment_with_kwargs['num_items_in_batch'] = kwargs['num_items_in_batch']
            cell_out, next_seg_kwargs = self.process_segment(segment_with_kwargs, next_seg_len=next_seg_len)
            if (not output_only_last_segment) or (seg_num == len(segmented) - 1):
                cell_outputs.append(cell_out)

        out = self.process_outputs(cell_outputs, labels=labels,
                                   labels_mask=labels_mask,
                                   output_attentions=output_attentions,
                                   output_hidden_states=output_hidden_states,
                                   num_items_in_batch=kwargs.get('num_items_in_batch'))

        if not self.training:
            self.memory_cell.zero_mem()
            self.last_state = None
        return out

    def segment(self, **kwargs):
        segments = []
        for k, tensor in kwargs.items():
            if tensor is not None:
                k_segments = self.split_tensor(tensor)
                for s, k_seg in enumerate(k_segments):
                    if s < len(segments):
                        segments[s][k] = k_seg
                    else:
                        segments.append({k: k_seg})
        return segments

    def split_tensor(self, tensor):
        align = self.rmt_config.get('segment_alignment')
        segment_size = self.rmt_config.get('segment_size')
        if align in {'left', None}:
            split_inds = list(range(0, tensor.shape[1], segment_size)) + [tensor.shape[1]]
            segments = [tensor[:, start:end] for (start, end) in zip(split_inds, split_inds[1:])]
        elif align in {'right', None}:
            split_inds = (list(range(tensor.shape[1], 0, -segment_size)) + [0])[::-1]
            segments = [tensor[:, start:end] for (start, end) in zip(split_inds, split_inds[1:])]
        elif align == 'center':
            n_seg = math.ceil(tensor.shape[1] / segment_size)
            segments = torch.chunk(tensor, n_seg, dim=1)
        else:
            raise NotImplementedError
        return segments

    def process_outputs(self, cell_outputs, **kwargs):
        out = CausalLMOutputWithCrossAttentions()
        full_logits = torch.cat([o.logits for o in cell_outputs], dim=1)

        labels = kwargs.get('labels')
        if labels is not None:
            labels = labels[:, -full_logits.size(1):]
            shift_labels = labels[..., 1:].contiguous()
            shift_logits = full_logits[..., :-1, :].contiguous()
            flat_labels = shift_labels.view(-1)
            flat_logits = shift_logits.view(-1, shift_logits.size(-1))

            labels_mask = kwargs.get('labels_mask')
            if labels_mask is not None:
                labels_mask = labels_mask[:, -full_logits.size(1):]
                shift_mask = labels_mask[..., :-1].contiguous()
                flat_labels = flat_labels[shift_mask.view(-1)]
                flat_logits = flat_logits[shift_mask.view(-1)]

            loss_fct = CrossEntropyLoss(reduction='sum')
            loss = loss_fct(flat_logits, flat_labels)
            if labels_mask is not None:
                denom = labels_mask[..., :-1].contiguous().view(-1).sum()
            else:
                denom = (flat_labels != -100).sum()
            denom = torch.clamp(denom, min=1)
            out['loss'] = loss / denom
        else:
            out['loss'] = 0
        if ('HF_Trainer' not in os.environ) or not os.environ['HF_Trainer']:
            out['ce_loss'] = out['loss']

        out['logits'] = full_logits
        segment_keys = ['loss', 'logits']
        if kwargs.get('output_attentions'):
            segment_keys.append('attentions')
        if kwargs.get('output_hidden_states'):
            full_hidden_states = tuple([torch.cat(layer_hs, dim=1) for layer_hs in zip(*[o.hidden_states for o in cell_outputs])])
            segment_keys.append('hidden_states')
            out['hidden_states'] = full_hidden_states
        if ('HF_Trainer' not in os.environ) or not os.environ['HF_Trainer']:
            for seg_num, o in enumerate(cell_outputs):
                for key, value in o.items():
                    if any([sk in key for sk in segment_keys]):
                        out[f'{key}_{seg_num}'] = value

        return out

    def generate(self, input_ids, attention_mask, **generate_kwargs):
        self.memory_cell.zero_mem()
        segmented = self.segment(input_ids=input_ids, attention_mask=attention_mask)
        next_seg_kwargs = dict()
        for seg_num, segment in enumerate(segmented[:-1]):
            next_seg_len = segmented[seg_num + 1]['input_ids'].size(-1)
            _, next_seg_kwargs = self.process_segment(dict(**segment, **next_seg_kwargs), next_seg_len=next_seg_len)

        final_segment = segmented[-1]
        assert next_seg_kwargs.get('past_key_values') is None or isinstance(next_seg_kwargs.get('past_key_values'), Cache), "Sliding Window generation is not implemented for legacy cache"
        if next_seg_kwargs.get('past_key_values') is not None:
            prev_attn_mask = segmented[-2]['attention_mask']
            legacy_cache = next_seg_kwargs['past_key_values'].to_legacy_cache()
            seg_len = segmented[-2]['input_ids'].size(-1)
            cache = DynamicCache().from_legacy_cache(legacy_cache)
            generate_kwargs['past_key_values'] = cache
            generate_kwargs['window_size'] = seg_len
            final_segment['prev_attn_mask'] = prev_attn_mask
            out = self.memory_cell.greedy_generate_sw(**final_segment, **generate_kwargs)
            return out
        else:
            out = self.memory_cell.generate(**final_segment, **generate_kwargs)
            return out


# ---- model.py ----
import math
import torch
from torch.nn import CrossEntropyLoss
from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions
from transformers.cache_utils import Cache, DynamicCache
from torch.nn.functional import relu as r
import torch.nn.functional as F
import os


class ARMTConfig(PretrainedConfig):
    model_type = "armt"

    def __init__(self,
                 base_model_name=None,
                 base_model_config=None,
                 num_mem_tokens=16,
                 d_mem=512,
                 segment_size=512,
                 segment_alignment="left",
                 sliding_window=False,
                 attend_to_previous_input=False,
                 use_sink=False,
                 layers_attr="model.layers",
                 wrap_pos=False,
                 correction=True,
                 n_heads=1,
                 use_denom=True,
                 gating=False,
                 freeze_mem=False,
                 **kwargs):
        super().__init__(**kwargs)
        if (base_model_name is not None) and (base_model_config is not None):
            raise ValueError("Exactly one of `base_model_name` or `base_model_config` must be provided. Set the other to None.")
        self.base_model_name = base_model_name
        self.base_model_config = base_model_config
        self.num_mem_tokens = num_mem_tokens
        self.d_mem = d_mem
        self.segment_size = segment_size
        self.segment_alignment = segment_alignment
        self.sliding_window = sliding_window
        self.attend_to_previous_input = attend_to_previous_input
        self.use_sink = use_sink
        self.layers_attr = layers_attr
        self.wrap_pos = wrap_pos
        self.correction = correction
        self.n_heads = n_heads
        self.use_denom = use_denom
        self.gating = gating
        self.freeze_mem = freeze_mem

    def get(self, attr: str, default=None):
        if hasattr(self, attr):
            return getattr(self, attr)
        else:
            return default


class ARMTForCausalLM(PreTrainedModel):
    config_class = ARMTConfig

    def __init__(self, config: ARMTConfig, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM

        base_model = None
        if getattr(config, 'base_model_name', None) is not None and getattr(config, 'base_model_config', None) is not None:
            raise ValueError("Exactly one of `base_model_name` or `base_model_config` must be provided in ARMTConfig.")
        bm_cfg = getattr(config, 'base_model_config', None)
        if bm_cfg is not None:
            if isinstance(bm_cfg, PretrainedConfig) and getattr(bm_cfg, 'model_type', None) != ARMTConfig.model_type:
                resolved_cfg = bm_cfg
            elif isinstance(bm_cfg, dict):
                if 'model_type' not in bm_cfg:
                    raise ValueError("`base_model_config` dict must include a 'model_type' key (e.g., 'gpt_neox', 'llama').")
                config_cls_or_instance = AutoConfig.for_model(bm_cfg['model_type'])
                if isinstance(config_cls_or_instance, PretrainedConfig):
                    resolved_cfg = config_cls_or_instance
                    for k, v in bm_cfg.items():
                        setattr(resolved_cfg, k, v)
                else:
                    resolved_cfg = config_cls_or_instance.from_dict(bm_cfg)
            elif isinstance(bm_cfg, str):
                resolved_cfg = AutoConfig.from_pretrained(bm_cfg)
            else:
                raise TypeError("`base_model_config` must be a transformers.PretrainedConfig, dict, or str (name/path)")
            base_model = AutoModelForCausalLM.from_config(resolved_cfg)
        elif getattr(config, 'base_model_name', None):
            base_model = AutoModelForCausalLM.from_pretrained(config.base_model_name)
        else:
            raise ValueError("ARMTForCausalLM requires either `base_model_config` or `base_model_name` in ARMTConfig.")

        self.armt_config = config

        memory_cell = AssociativeMemoryCell(
            base_model=base_model,
            num_mem_tokens=config.num_mem_tokens,
            d_mem=config.d_mem,
            layers_attr=config.layers_attr,
            wrap_pos=config.wrap_pos,
            correction=config.correction,
            n_heads=config.n_heads,
            use_denom=config.use_denom,
            gating=config.gating,
            freeze_mem=config.freeze_mem,
            attend_to_previous_input=config.attend_to_previous_input,
            use_sink=config.use_sink,
        )

        self.armt = AssociativeRecurrentWrapper(
            memory_cell,
            segment_size=config.segment_size,
            segment_alignment=config.segment_alignment,
            sliding_window=config.sliding_window,
            attend_to_previous_input=config.attend_to_previous_input,
        )

    def forward(
        self,
        input_ids=None,
        labels=None,
        labels_mask=None,
        inputs_embeds=None,
        attention_mask=None,
        output_attentions=None,
        output_hidden_states=None,
        input_segmented=False,
        output_only_last_segment=False,
        num_items_in_batch=None,
    ):
        return self.armt(
            input_ids=input_ids,
            labels=labels,
            labels_mask=labels_mask,
            inputs_embeds=inputs_embeds,
            attention_mask=attention_mask,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            input_segmented=input_segmented,
            output_only_last_segment=output_only_last_segment,
            num_items_in_batch=num_items_in_batch,
        )

    def generate(self, *args, **kwargs):
        return self.armt.generate(*args, **kwargs)

    def load_state_dict(self, state_dict, strict=True, assign=False):
        try:
            return super().load_state_dict(state_dict, strict, assign)
        except RuntimeError:
            print("Failed to load state, retrying with ARMT loader.")
            self.armt.load_state_dict(state_dict, strict=True, assign=assign)
            print("Success!")

    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, config=None, *args, **kwargs):
        return super().from_pretrained(pretrained_model_name_or_path, *args, config=config, **kwargs)

    def gradient_checkpointing_enable(self, *args, **kwargs):
        self.armt.gradient_checkpointing_enable(*args, **kwargs)
