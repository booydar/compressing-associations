import math
import torch
from torch.nn import CrossEntropyLoss

from transformers import StoppingCriteria
from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions


# Classic RMT
# ================================================

class RMTConfig(PretrainedConfig):
    model_type = "rmt"

    def __init__(self,
                 base_model_name="HuggingFaceTB/SmolLM2-135M",
                 base_model_config=None,
                 from_pretrained=None,
                 num_mem_tokens=16,
                 max_n_segments=10,
                 think_token_id=None,
                 answer_token_id=None,
                 bos_token_id=None,
                 eos_token_id=None,
                 **kwargs):
        super().__init__(**kwargs)
        self.base_model_name = base_model_name
        self.base_model_config = base_model_config
        self.from_pretrained = from_pretrained
        self.num_mem_tokens = num_mem_tokens
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id
        self.memory_cell_cls = "MemoryCell"
        self.recurrent_wrapper_cls = "RecurrentWrapperNoSegmentationGenerate"

    def get(self, attr: str, default=None):
        if hasattr(self, attr):
            return getattr(self, attr)
        else:
            return default


class RMTForReasoning(PreTrainedModel):
    config_class = RMTConfig

    def __init__(self, config: RMTConfig, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM
        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(config.from_pretrained)
        else:
            if config.base_model_config is None:
                base_config = AutoConfig.from_pretrained(config.base_model_name)
            else:
                base_config = config.base_model_config
            base_model = AutoModelForCausalLM.from_config(base_config)

        self.rmt_config = config
        memory_cell = MemoryCell(base_model, num_mem_tokens=config.num_mem_tokens)
        self.rmt = RecurrentWrapperNoSegmentationGenerate(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id
        )

    def forward(self, labels=None, *args, **kwargs):
        return self.rmt(labels=labels, *args, **kwargs)

    def generate(self, *args, **kwargs):
        return self.rmt.generate(*args, **kwargs)

    def load_state_dict(self, state_dict, strict=True, assign=False):
        try:
            return super().load_state_dict(state_dict, strict, assign)
        except RuntimeError:
            print("Failed to load state, retrying with RMT loader.")
            self.rmt.load_state_dict(state_dict, strict=True, assign=assign)
            print("Success!")

    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, config=None, *args, **kwargs):
        from transformers.utils.hub import cached_file, HfHubHTTPError
        import torch

        if config is None:
            config = RMTConfig.from_pretrained(pretrained_model_name_or_path, **kwargs)

        model = cls(config)

        state_dict = None
        try:
            weights_path = cached_file(pretrained_model_name_or_path, "model.safetensors", **kwargs)
            from safetensors.torch import load_file
            state_dict = load_file(weights_path, device="cpu")
        except (OSError, HfHubHTTPError):
            try:
                weights_path = cached_file(pretrained_model_name_or_path, "pytorch_model.bin", **kwargs)
                state_dict = torch.load(weights_path, map_location="cpu")
            except (OSError, HfHubHTTPError):
                print(f"Warning: Could not find weights for {pretrained_model_name_or_path}. "
                      f"The model is initialized randomly.")

        if state_dict is not None:
            model.load_state_dict(state_dict, strict=False)

        return model


class MemoryCell(torch.nn.Module):
    def __init__(self, base_model, num_mem_tokens):
        super().__init__()
        self.model = base_model
        self.create_memory(num_mem_tokens)

    def create_memory(self, num_mem_tokens):
        self.num_mem_tokens = num_mem_tokens
        embeddings = self.model.get_input_embeddings()
        memory_dim = getattr(self.model.config, 'n_embd', self.model.config.hidden_size)
        memory_weights = torch.randn((num_mem_tokens, memory_dim)) * embeddings.weight.data.std()
        self.register_parameter('memory', torch.nn.Parameter(memory_weights, requires_grad=True))

        self.read_memory_position = range(num_mem_tokens)
        self.write_memory_position = range(-num_mem_tokens, 0)

    def set_memory(self, input_shape):
        memory = self.memory.repeat(input_shape[0], 1, 1)
        return memory

    def forward(self, input_ids, memory_state=None, **kwargs):
        if memory_state is None:
            memory_state = self.set_memory(input_ids.shape)

        seg_kwargs = self.process_input(input_ids, memory_state, write_mem=True, **kwargs)
        out = self.model(**seg_kwargs)
        out, new_memory_state = self.process_output(out, **kwargs)

        return out, new_memory_state

    def generate(self, input_ids, memory_state, attention_mask=None, **generate_kwargs):
        if memory_state is None:
            memory_state = self.set_memory(input_ids.shape)

        seg_kwargs = self.process_input(input_ids, memory_state, attention_mask=attention_mask, write_mem=False)
        out = self.model.generate(inputs_embeds=seg_kwargs['inputs_embeds'],
                                  attention_mask=seg_kwargs['attention_mask'],
                                  **generate_kwargs)
        return out

    def process_input(self, input_ids, memory_state, write_mem, **kwargs):
        seg_kwargs = dict(**kwargs)

        inputs_embeds = kwargs.get('inputs_embeds')
        if inputs_embeds is None:
            inputs_embeds = self.model.get_input_embeddings()(input_ids)

        if self.num_mem_tokens > 0:
            if write_mem:
                inputs_embeds = torch.cat([memory_state, inputs_embeds, memory_state], dim=1)
            else:
                inputs_embeds = torch.cat([memory_state, inputs_embeds], dim=1)

        seg_kwargs['input_ids'] = None
        seg_kwargs['inputs_embeds'] = inputs_embeds
        if kwargs.get('attention_mask') is not None:
            seg_kwargs['attention_mask'] = self.pad_attention_mask(kwargs['attention_mask'], inputs_embeds.shape)
        seg_kwargs['output_hidden_states'] = True
        return seg_kwargs

    def pad_attention_mask(self, attention_mask, shape):
        if self.num_mem_tokens in {0, None}:
            return attention_mask
        else:
            mask = torch.ones(*shape[:2], dtype=torch.int64).to(attention_mask.device)
            mask[:, self.num_mem_tokens: self.num_mem_tokens + attention_mask.shape[1]] = attention_mask
            return mask

    def process_output(self, model_outputs, **kwargs):
        if self.num_mem_tokens not in {0, None}:
            out = CausalLMOutputWithCrossAttentions()
            memory_state = model_outputs.hidden_states[-1][:, -self.num_mem_tokens:]
            out['logits'] = model_outputs.logits[:, self.num_mem_tokens:-self.num_mem_tokens]

            if kwargs.get('output_hidden_states'):
                out['hidden_states'] = [lh[:, self.num_mem_tokens:-self.num_mem_tokens]
                                        for lh in model_outputs.hidden_states]
            if kwargs.get('output_attentions'):
                out['attentions'] = model_outputs['attentions']
        else:
            memory_state = None
            out = model_outputs

        return out, memory_state


class RecurrentWrapper(torch.nn.Module):
    def __init__(self, memory_cell, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.rmt_config = rmt_kwargs

    def forward(self, input_ids, labels=None, labels_mask=None, inputs_embeds=None, attention_mask=None,
                output_attentions=None, output_hidden_states=None):
        memory_state = None
        segmented = self.segment(input_ids=input_ids, inputs_embeds=inputs_embeds, attention_mask=attention_mask)

        cell_outputs = []
        for seg_num, segment in enumerate(segmented):
            cell_out, memory_state = self.memory_cell(**segment, memory_state=memory_state, output_hidden_states=True)
            cell_outputs.append(cell_out)
            memory_state = self.manage_gradients(memory_state, seg_num)

        out = self.process_outputs(cell_outputs, labels=labels,
                                   labels_mask=labels_mask,
                                   output_attentions=output_attentions,
                                   output_hidden_states=output_hidden_states)
        return out

    def generate(self, input_ids, attention_mask=None, **generate_kwargs):
        memory_state = None
        segmented = self.segment(input_ids=input_ids, attention_mask=attention_mask)

        for seg_num, segment in enumerate(segmented[:-1]):
            cell_out, memory_state = self.memory_cell(**segment, memory_state=memory_state, output_hidden_states=True)

        final_segment = segmented[-1]
        out = self.memory_cell.generate(**final_segment, memory_state=memory_state, **generate_kwargs)

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
        full_hidden_states = tuple([torch.cat(layer_hs, dim=1)
                                    for layer_hs in zip(*[o.hidden_states for o in cell_outputs])])

        labels = kwargs.get('labels')
        if labels is not None:
            shift_labels = labels[..., 1:].contiguous()
            shift_logits = full_logits[..., :-1, :].contiguous()
            flat_labels = shift_labels.view(-1)
            flat_logits = shift_logits.view(-1, shift_logits.size(-1))

            loss_fct = CrossEntropyLoss()
            labels_mask = kwargs.get('labels_mask')
            if labels_mask is not None:
                shift_mask = labels_mask[..., :-1].contiguous()

                flat_labels = flat_labels[shift_mask.view(-1)]
                flat_logits = flat_logits[shift_mask.view(-1)]

            out['loss'] = loss_fct(flat_logits, flat_labels)
        else:
            out['loss'] = 0

        out['logits'] = full_logits
        segment_keys = ['loss', 'logits']
        if kwargs.get('output_attentions'):
            segment_keys.append('attentions')
        if kwargs.get('output_hidden_states'):
            segment_keys.append('hidden_states')
            out['hidden_states'] = full_hidden_states

        return out

    def manage_gradients(self, memory_state, seg_num):
        k2, max_n_segments = self.rmt_config.get('k2'), self.rmt_config.get('max_n_segments')
        if seg_num == 0 \
            or k2 in {-1, None} \
                or seg_num + k2 > max_n_segments:
            return memory_state

        memory_state = memory_state.detach()
        return memory_state

    def gradient_checkpointing_enable(self, *args, **kwargs):
        self.memory_cell.model.gradient_checkpointing_enable(*args, **kwargs)


class RecurrentWrapperNoSegmentation(RecurrentWrapper):
    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None):
        memory_state = None

        cell_outputs = []
        for seg_num, segment in enumerate(segments):
            cell_out, memory_state = self.memory_cell(input_ids=segment['input_ids'],
                                                      attention_mask=segment['attention_mask'],
                                                      memory_state=memory_state, output_hidden_states=True)
            cell_outputs.append(cell_out)
            memory_state = self.manage_gradients(memory_state, seg_num)

        out = self.process_outputs(cell_outputs, segments,
                                   output_attentions=output_attentions,
                                   output_hidden_states=output_hidden_states)
        return out

    def generate(self, segments, **generate_kwargs):
        raise NotImplementedError("Generation not implemented for this wrapper.")

    def process_outputs(self, cell_outputs, segments, **kwargs):
        out = CausalLMOutputWithCrossAttentions()
        proxy_out = {}
        for seg_num, segment in enumerate(segments):
            cell_out = cell_outputs[seg_num]

            full_logits = cell_out.logits

            labels = segment.get('labels')
            if labels is not None:
                shift_labels = labels[..., 1:].contiguous()
                shift_logits = full_logits[..., :-1, :].contiguous()
                flat_labels = shift_labels.view(-1)
                flat_logits = shift_logits.view(-1, shift_logits.size(-1))

                loss_fct = CrossEntropyLoss()
                labels_mask = segment.get('labels_mask')
                if labels_mask is not None:
                    shift_mask = labels_mask[..., :-1].contiguous()

                    flat_labels = flat_labels[shift_mask.view(-1)]
                    flat_logits = flat_logits[shift_mask.view(-1)]

                    if labels_mask.sum() == 0:
                        loss_value = 0
                    else:
                        loss_value = loss_fct(flat_logits, flat_labels)

                proxy_out[f'loss_{seg_num}'] = loss_value
            else:
                proxy_out[f'loss_{seg_num}'] = 0

            segment_keys = ['loss']
            if kwargs.get('output_attentions'):
                segment_keys.append('attentions')
            if kwargs.get('output_hidden_states'):
                segment_keys.append('hidden_states')

            for key, value in cell_out.items():
                if any([sk in key for sk in segment_keys]):
                    proxy_out[f'{key}_{seg_num}'] = value

        num_segments = len(segments)
        out['loss'] = sum([proxy_out[f'loss_{seg_num}'] for seg_num in range(num_segments)]) / num_segments
        out['logits'] = torch.cat([cell_out.logits for cell_out in cell_outputs], dim=1)
        # print(out.keys(), out.loss)

        return out

    def gradient_checkpointing_enable(self, *args, **kwargs):
        if hasattr(self.memory_cell.model, "gradient_checkpointing_enable"):
            return self.memory_cell.model.gradient_checkpointing_enable(*args, **kwargs)


class StopOnSpecialTokenCriteria(StoppingCriteria):
    def __init__(self, special_token_ids):
        self.special_token_ids = set(special_token_ids)

    def __call__(self, input_ids, scores, **kwargs):
        last_token = input_ids[0, -1].item()
        return last_token in self.special_token_ids


class RecurrentWrapperNoSegmentationGenerate(RecurrentWrapperNoSegmentation):
    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None, *args, **kwargs):
        memory_state = None

        cell_outputs = []
        for seg_num, segment in enumerate(segments):
            cell_out, memory_state = self.memory_cell(input_ids=segment['input_ids'],
                                                      attention_mask=segment['attention_mask'],
                                                      memory_state=memory_state, output_hidden_states=True)
            cell_outputs.append(cell_out)
            self.manage_gradients(memory_state, seg_num)

        out = self.process_outputs(cell_outputs, segments,
                                   output_attentions=output_attentions,
                                   output_hidden_states=output_hidden_states)
        return out

    def generate(self, segments, **kwargs):
        memory_state = None

        for seg_num, segment in enumerate(segments):
            cell_out, memory_state = self.memory_cell(input_ids=segment['input_ids'],
                                                      attention_mask=segment['attention_mask'],
                                                      memory_state=memory_state, output_hidden_states=True)

        generated_segments = []
        for seg_num in range(len(segments), self.rmt_config.get("max_n_segments", 32)):
            output_ids, memory_state = self.generate_segment(memory_state=memory_state, **kwargs)
            generated_segments.append(output_ids)

            if self.all_done(generated_segments):
                break

        return generated_segments

    def generate_segment(self, memory_state, **kwargs):
        input_ids = self.get_bos_tensor(memory_state)
        attention_mask = torch.ones_like(input_ids).bool()

        generated = self.memory_cell.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            memory_state=memory_state,
            stopping_criteria=self.make_custom_stopping_criteria(),
            **kwargs
        )

        # Update memory state from generation
        fwd_inputs = torch.cat((input_ids, generated), dim=1)[:, :-1]
        _, memory_state = self.memory_cell(input_ids=fwd_inputs, memory_state=memory_state)

        return generated, memory_state

    def get_bos_tensor(self, memory_state):
        bos = self.rmt_config["bos_token_id"]
        bos_tensor = torch.tensor([bos] * memory_state.shape[0]).reshape(-1, 1)
        return bos_tensor.to(memory_state.device)

    def all_done(self, generated_segments):
        eos = self.rmt_config['eos_token_id']
        bs = generated_segments[0].shape[0]
        have_eos = [any([eos in seg[i] for seg in generated_segments]) for i in range(bs)]
        all_done = all(have_eos)
        return all_done

    def make_custom_stopping_criteria(self):
        return [StopOnSpecialTokenCriteria([self.rmt_config['think_token_id'], self.rmt_config['answer_token_id']])]


# ================================================
# Variable Layer RMT
# ================================================

class RMTVLForReasoning(RMTForReasoning):
    def __init__(self, config: RMTConfig, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM
        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(config.from_pretrained)
        else:
            if config.base_model_config is None:
                base_config = AutoConfig.from_pretrained(config.base_model_name)
            else:
                base_config = config.base_model_config
            base_model = AutoModelForCausalLM.from_config(base_config)

        self.rmt_config = config
        memory_cell = MemoryCellVariableLayer(base_model, num_mem_tokens=config.num_mem_tokens, out_layer_idx=config.out_layer_idx)
        self.rmt = RecurrentWrapperNoSegmentationGenerate(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id
        )


class MemoryCellVariableLayer(MemoryCell):
    def __init__(self, base_model, num_mem_tokens, out_layer_idx):
        super().__init__(base_model, num_mem_tokens)
        self.out_layer_idx = out_layer_idx

    def process_output(self, model_outputs, **kwargs):
        if self.num_mem_tokens not in {0, None}:
            out = CausalLMOutputWithCrossAttentions()
            memory_state = model_outputs.hidden_states[self.out_layer_idx][:, -self.num_mem_tokens:]
            out['logits'] = model_outputs.logits[:, self.num_mem_tokens:-self.num_mem_tokens]

            if kwargs.get('output_hidden_states'):
                out['hidden_states'] = [lh[:, self.num_mem_tokens:-self.num_mem_tokens]
                                        for lh in model_outputs.hidden_states]
            if kwargs.get('output_attentions'):
                out['attentions'] = model_outputs['attentions']
        else:
            memory_state = None
            out = model_outputs

        return out, memory_state

# ================================================
# 4d attention mask support
# position ids support
# ================================================


class MemoryCellSlidingWindow(MemoryCell):
    def process_input(self, input_ids, memory_state, write_mem, **kwargs):
        seg_kwargs = dict(**kwargs)

        inputs_embeds = kwargs.get('inputs_embeds')
        if inputs_embeds is None:
            inputs_embeds = self.model.get_input_embeddings()(input_ids)

        if self.num_mem_tokens > 0:
            if write_mem:
                inputs_embeds = torch.cat([memory_state, inputs_embeds, memory_state], dim=1)
            else:
                inputs_embeds = torch.cat([memory_state, inputs_embeds], dim=1)

        seg_kwargs['input_ids'] = None
        seg_kwargs['inputs_embeds'] = inputs_embeds
        if kwargs.get('attention_mask') is not None:
            seg_kwargs['attention_mask'] = self.pad_attention_mask(kwargs['attention_mask'], inputs_embeds.shape)
        
        # Add this to handle position_ids
        if kwargs.get('position_ids') is not None:
            seg_kwargs['position_ids'] = self.pad_position_ids(kwargs['position_ids'], inputs_embeds.shape, write_mem)
        
        seg_kwargs['output_hidden_states'] = True
        return seg_kwargs

    def pad_position_ids(self, position_ids, shape, write_mem):
        """Pad position_ids to account for memory tokens."""
        if self.num_mem_tokens in {0, None}:
            return position_ids
        
        # Memory tokens get position 0
        bs, seq_len = shape[:2]
        device = position_ids.device
        dtype = position_ids.dtype
        
        if write_mem:
            # [mem_tokens, original_positions, mem_tokens]
            mem_pos = torch.zeros(bs, self.num_mem_tokens, dtype=dtype, device=device)
            padded = torch.cat([mem_pos, position_ids, mem_pos], dim=1)
        else:
            # [mem_tokens, original_positions]
            mem_pos = torch.zeros(bs, self.num_mem_tokens, dtype=dtype, device=device)
            padded = torch.cat([mem_pos, position_ids], dim=1)
        
        return padded

    def pad_attention_mask(self, attention_mask, shape):
        if self.num_mem_tokens in {0, None}:
            return attention_mask
        else:
            if len(attention_mask.shape) == 2:
                # 2D mask (bs, l) → pad to (bs, L_total)
                bs, L_total = shape[:2]
                mask = torch.ones(bs, L_total, dtype=attention_mask.dtype, device=attention_mask.device)
                l = attention_mask.shape[1]
                mask[:, self.num_mem_tokens:self.num_mem_tokens + l] = attention_mask
                return mask
            else:
                # Handle both 3D (bs, l, l) and 4D (bs, 1, l, l) token-by-token masks
                # If 3D, unsqueeze to 4D for uniform processing
                if len(attention_mask.shape) == 3:
                    attention_mask = attention_mask.unsqueeze(1)  # (bs, l, l) → (bs, 1, l, l)

                # Convert integer masks to float additive masks for SDPA compatibility
                # Integer mask: 1 = attend, 0 = don't attend
                # Float additive mask: 0 = attend, -inf = don't attend
                device = attention_mask.device
                if not attention_mask.dtype.is_floating_point:
                    # Convert binary mask (1=attend, 0=block) to additive mask (0=attend, -inf=block)
                    attention_mask = attention_mask.to(torch.float32)
                    attention_mask = torch.where(
                        attention_mask > 0.5,
                        torch.tensor(0.0, device=device),
                        torch.tensor(float('-inf'), device=device)
                    )

                # 4D additive mask (bs, 1, l, l) → pad to (bs, 1, L_total, L_total)
                bs, L_total = shape[:2]
                dtype = attention_mask.dtype
                min_val = torch.finfo(dtype).min

                l = attention_mask.shape[-1]
                start = self.num_mem_tokens
                end = start + l

                # base causal over full length (zeros allowed, -inf disallowed)
                idx = torch.arange(L_total, device=device)
                allow = idx[None, None, :, None] >= idx[None, None, None, :]
                full = torch.full((bs, 1, L_total, L_total), min_val, dtype=dtype, device=device)
                full = torch.where(allow, torch.tensor(0.0, dtype=dtype, device=device), full)

                # embed the provided sliding-window (segment-to-segment) block
                full[:, :, start:end, start:end] = attention_mask
                return full


class RecurrentWrapperNoSegmentationGeneratePosSupport(RecurrentWrapperNoSegmentationGenerate):
    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None, *args, **kwargs):
        memory_state = None

        cell_outputs = []
        for seg_num, segment in enumerate(segments):
            # if segment.get('position_ids') is not None:
            #     print(f"\n\nPosition ids: {segment['position_ids']}\n\n")
            cell_out, memory_state = self.memory_cell(input_ids=segment['input_ids'],
                                                      attention_mask=segment['attention_mask'],
                                                      position_ids=segment['position_ids'],
                                                      memory_state=memory_state, output_hidden_states=True)
            cell_outputs.append(cell_out)
            self.manage_gradients(memory_state, seg_num)

        out = self.process_outputs(cell_outputs, segments,
                                   output_attentions=output_attentions,
                                   output_hidden_states=output_hidden_states)
        return out

    def generate(self, segments, **kwargs):
        memory_state = None

        for seg_num, segment in enumerate(segments):
            cell_out, memory_state = self.memory_cell(input_ids=segment['input_ids'],
                                                      attention_mask=segment['attention_mask'],
                                                      position_ids=segment['position_ids'],
                                                      memory_state=memory_state, output_hidden_states=True)

        generated_segments = []
        for seg_num in range(len(segments), self.rmt_config.get("max_n_segments", 32)):
            output_ids, memory_state = self.generate_segment(memory_state=memory_state, **kwargs)
            generated_segments.append(output_ids)

            if self.all_done(generated_segments):
                break

        return generated_segments

class RMTSlidingWindowForReasoning(RMTForReasoning):
    def __init__(self, config: RMTConfig, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM
        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(config.from_pretrained)
        else:
            if config.base_model_config is None:
                base_config = AutoConfig.from_pretrained(config.base_model_name)
            else:
                base_config = config.base_model_config
            base_model = AutoModelForCausalLM.from_config(base_config)

        self.rmt_config = config
        memory_cell = MemoryCellSlidingWindow(base_model, num_mem_tokens=config.num_mem_tokens)
        self.rmt = RecurrentWrapperNoSegmentationGeneratePosSupport(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id
        )

# ================================================
# memory evenly distributed
# ================================================

class MemoryCellWithSpreadPositions(MemoryCell):
    """Memory tokens get position_ids evenly spread across the content range,
    so every content token perceives some memory token as positionally close."""

    def process_input(self, input_ids, memory_state, write_mem, **kwargs):
        seg_kwargs = dict(**kwargs)

        inputs_embeds = kwargs.get('inputs_embeds')
        if inputs_embeds is None:
            inputs_embeds = self.model.get_input_embeddings()(input_ids)

        N = inputs_embeds.shape[1]  # content sequence length
        M = self.num_mem_tokens
        device = inputs_embeds.device

        if M > 0:
            if write_mem:
                inputs_embeds = torch.cat([memory_state, inputs_embeds, memory_state], dim=1)

                # Content: standard sequential [0, 1, ..., N-1]
                content_pos = torch.arange(N, device=device)
                # Left memory: evenly spread across content range
                left_mem_pos = torch.linspace(0, N - 1, M, device=device).long()
                # Right memory: evenly spread (offset by half step)
                step = N / M
                right_mem_pos = torch.linspace(step / 2, N - 1 - step / 2, M, device=device).long()

                position_ids = torch.cat([left_mem_pos, content_pos, right_mem_pos])
            else:
                inputs_embeds = torch.cat([memory_state, inputs_embeds], dim=1)
                content_pos = torch.arange(N, device=device)
                left_mem_pos = torch.linspace(0, N - 1, M, device=device).long()
                position_ids = torch.cat([left_mem_pos, content_pos])

            position_ids = position_ids.unsqueeze(0).expand(inputs_embeds.shape[0], -1)
        else:
            position_ids = None

        seg_kwargs['input_ids'] = None
        seg_kwargs['inputs_embeds'] = inputs_embeds
        if position_ids is not None:
            seg_kwargs['position_ids'] = position_ids
        if kwargs.get('attention_mask') is not None:
            seg_kwargs['attention_mask'] = self.pad_attention_mask(kwargs['attention_mask'], inputs_embeds.shape)
        seg_kwargs['output_hidden_states'] = True
        return seg_kwargs

class RMTWithSpreadPositionsForReasoning(RMTForReasoning):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM
        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(config.from_pretrained)
        else:
            if config.base_model_config is None:
                base_config = AutoConfig.from_pretrained(config.base_model_name)
            else:
                base_config = config.base_model_config
            base_model = AutoModelForCausalLM.from_config(base_config)

        self.rmt_config = config
        memory_cell = MemoryCellWithSpreadPositions(base_model, num_mem_tokens=config.num_mem_tokens)
        self.rmt = RecurrentWrapperNoSegmentationGenerate(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id
        )

# ================================================
# memory no positional encoding
# ================================================

class MemoryCellNoPosEnc(MemoryCell):
    """Memory tokens receive no positional encoding.
    
    GPT-2: pre-subtracts wpe(0) from memory embeddings so the model's
           addition of wpe(position_ids=0) cancels out → net zero pos enc.
    RoPE (Pythia/Llama): position_ids=0 → identity rotation (no rotation applied).
    
    Content tokens always get standard positions [0, 1, ..., N-1].
    """

    def _has_absolute_pos_emb(self):
        """Check if model uses absolute position embeddings (GPT-2 style)."""
        return hasattr(self.model, 'transformer') and hasattr(self.model.transformer, 'wpe')

    def process_input(self, input_ids, memory_state, write_mem, **kwargs):
        seg_kwargs = dict(**kwargs)

        inputs_embeds = kwargs.get('inputs_embeds')
        if inputs_embeds is None:
            inputs_embeds = self.model.get_input_embeddings()(input_ids)

        N = inputs_embeds.shape[1]  # content sequence length
        M = self.num_mem_tokens
        device = inputs_embeds.device

        if M > 0:
            # For GPT-2: cancel the wpe(0) that the model will add to memory positions
            if self._has_absolute_pos_emb():
                pos_zero = torch.zeros(1, dtype=torch.long, device=device)
                pos0_embed = self.model.transformer.wpe(pos_zero)  # (1, hidden_dim)
                memory_state_adj = memory_state - pos0_embed.unsqueeze(0)  # broadcast over (batch, M, hidden_dim)
            else:
                # RoPE models: position 0 = identity rotation, nothing extra needed
                memory_state_adj = memory_state

            # Build position_ids: all memory at 0, content at [0..N-1]
            content_pos = torch.arange(N, dtype=torch.long, device=device)
            mem_pos = torch.zeros(M, dtype=torch.long, device=device)

            if write_mem:
                inputs_embeds = torch.cat([memory_state_adj, inputs_embeds, memory_state_adj], dim=1)
                position_ids = torch.cat([mem_pos, content_pos, mem_pos])
            else:
                inputs_embeds = torch.cat([memory_state_adj, inputs_embeds], dim=1)
                position_ids = torch.cat([mem_pos, content_pos])

            position_ids = position_ids.unsqueeze(0).expand(inputs_embeds.shape[0], -1)
        else:
            position_ids = None

        seg_kwargs['input_ids'] = None
        seg_kwargs['inputs_embeds'] = inputs_embeds
        if position_ids is not None:
            seg_kwargs['position_ids'] = position_ids
        if kwargs.get('attention_mask') is not None:
            seg_kwargs['attention_mask'] = self.pad_attention_mask(kwargs['attention_mask'], inputs_embeds.shape)
        seg_kwargs['output_hidden_states'] = True
        return seg_kwargs

class RMTNoPosEncForReasoning(RMTForReasoning):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM
        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(config.from_pretrained)
        else:
            if config.base_model_config is None:
                base_config = AutoConfig.from_pretrained(config.base_model_name)
            else:
                base_config = config.base_model_config
            base_model = AutoModelForCausalLM.from_config(base_config)

        self.rmt_config = config
        memory_cell = MemoryCellNoPosEnc(base_model, num_mem_tokens=config.num_mem_tokens)
        self.rmt = RecurrentWrapperNoSegmentationGenerate(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id
        )